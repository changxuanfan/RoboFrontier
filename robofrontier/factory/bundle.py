"""Portable, checksummed factory inputs. No inference or physics execution."""
from copy import deepcopy
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import time
import urllib.request
from ..io import file_sha256 as digest

SCHEMA = 'robofrontier.factory-data.v1'
PATH_FIELDS = ('directory', 'recording', 'edit', 'derived_track')
# Mosaic desks a Factory bundle may display: R14 (81 mm grid; the published Factory
# data and its Oracle recordings) and R15 (71 mm grid; the current release).
MOSAIC_DISPLAY_REVISIONS = (14, 15)


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def inside(root, name):
    """Only data-relative, non-symlink paths may enter a portable manifest."""
    value = PurePosixPath(name)
    if not name or value.is_absolute() or '..' in value.parts or '\\' in name:
        raise ValueError('Unsafe bundle path: ' + str(name))
    root = Path(root).resolve()
    path = root.joinpath(*value.parts)
    if not path.resolve().is_relative_to(root):
        raise ValueError('Bundle path escapes data root: ' + name)
    cursor = path
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError('Symlinked bundle input: ' + name)
        cursor = cursor.parent
    return path


def resolved_release(root):
    root = Path(root).resolve()
    manifest = read(root/'bundle.json')
    release = read(inside(root, manifest['release']))
    for family in release['families'].values():
        for spec in family['oracle']:
            for field in PATH_FIELDS:
                if field in spec:
                    spec[field] = str(inside(root, spec[field]))
    return release


def verify(root, cases=None):
    root = Path(root).resolve()
    manifest = read(root/'bundle.json')
    if manifest.get('schema') != SCHEMA:
        raise ValueError('Unsupported factory bundle')
    files = manifest['files']
    if not files or 'bundle.json' in files:
        raise ValueError('Invalid bundle inventory')
    release_path=inside(root,manifest['release'])
    if digest(release_path)!=files[manifest['release']]['sha256']:
        raise ValueError('Factory release checksum mismatch')
    release=resolved_release(root)
    all_specs=[s for f in release['families'].values() for s in f['oracle']]
    all_ids=[s['id'] for s in all_specs]
    if len(set(all_ids))!=len(all_ids):raise ValueError('Duplicate factory station')
    walks=[root]
    required=set()
    if cases is not None:
        cases=set(cases)
        if not cases or cases-set(all_ids):raise ValueError('Unknown selected factory station')
        # Each render validates every byte it can consume, without rereading the
        # unrelated recordings of the other desks on a shared filesystem.
        walks=[inside(root,manifest['scene']).parent,inside(root,manifest['asset'])]
        required={manifest['release'],manifest['cameras']}
        for spec in all_specs:
            if spec['id'] not in cases:continue
            for field in PATH_FIELDS:
                if field in spec:
                    path=Path(spec[field]);walks.append(path.parent if field=='edit' else path)
            edit=read(spec['edit'])
            for name in edit.get('input_evidence_sha256',{}):
                if name not in ('actions.json','process.jsonl'):raise ValueError('Unexpected semantic evidence')
                required.add((Path(spec['recording']).parent/name).relative_to(root).as_posix())
        prefixes={p.relative_to(root).as_posix().rstrip('/')+'/' for p in walks}
        files={name:spec for name,spec in files.items() if name in required or any(name.startswith(prefix) for prefix in prefixes)}
    actual = set()
    for folder in set(walks):
        for path in folder.rglob('*'):
            if path.is_symlink():
                raise ValueError('Symlinked bundle input: ' + str(path))
            if path.is_file() and path != root/'bundle.json':
                actual.add(path.relative_to(root).as_posix())
    for name in required:
        if inside(root,name).is_file():actual.add(name)
    if actual != set(files):
        raise ValueError('Bundle inventory differs; missing or extra files')
    inode_hashes={}
    for name, spec in files.items():
        # The inventory was matched to actual regular paths above. Avoid resolving
        # every ancestor again for each of the many small recording chunks.
        path = root/name
        stat=path.stat();key=(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns)
        if key not in inode_hashes:inode_hashes[key]=digest(path)
        if stat.st_size != spec['bytes'] or inode_hashes[key] != spec['sha256']:
            raise ValueError('Factory bundle checksum mismatch: ' + name)
    def checked_digest(path):
        name=Path(path).relative_to(root).as_posix()
        if name not in files:raise ValueError('Required file missing from bundle inventory: '+name)
        return files[name]['sha256']
    scene = inside(root, manifest['scene'])
    if read(scene.parent/'manifest.json')['scene_sha256'] != digest(scene):
        raise ValueError('Factory scene identity differs')
    asset = inside(root, manifest['asset'])
    if read(asset/'scene.json')['source_scene_sha256'] != digest(scene):
        raise ValueError('Blender asset does not match factory scene')
    cameras = read(inside(root, manifest['cameras']))
    camera_ids = [c['id'] for c in cameras]
    if len(camera_ids) != len(set(camera_ids)):
        raise ValueError('Duplicate factory camera')
    ids = set()
    for family in release['families'].values():
        for spec in family['oracle']:
            if cases is not None and spec['id'] not in cases:continue
            if spec['id'] in ids:
                raise ValueError('Duplicate factory station')
            ids.add(spec['id'])
            if digest(spec['edit']) != spec['edit_sha256']:
                raise ValueError('Station edit identity differs: ' + spec['id'])
            stream = read(Path(spec['recording'])/'stream.json')
            edit = read(spec['edit'])
            recorded = spec.get('recorded_case_id', spec['id'])
            if stream['case_id'] != recorded or edit['case_id'] != recorded:
                raise ValueError('Station recorded task identity differs')
            if edit['source_scene_sha256'] != stream['source_scene_sha256']:
                raise ValueError('Edit/recording source identity differs')
            if edit.get('schema')=='robofrontier.station-edit.v2':
                if (edit['source_stream_sha256']!=checked_digest(Path(spec['recording'])/'stream.json')
                        or edit['events_sha256']!=checked_digest(Path(spec['recording'])/'events.jsonl')
                        or edit['selection_sha256']!=checked_digest(inside(Path(spec['edit']).parent,edit['selection_file']))):
                    raise ValueError('Station edit source or selection differs')
            if digest(Path(spec['recording'])/'source/scene.xml') != stream['source_scene_sha256']:
                raise ValueError('Recorded source scene differs')
            for chunk in stream['chunks']:
                if checked_digest(inside(spec['recording'],chunk['file'])) != chunk['sha256']:
                    raise ValueError('Recorded motion chunk differs')
            source = Path(spec['directory'])
            if digest(source/'scene.xml') != read(source/'workstation.json')['scene_sha256']:
                raise ValueError('Display source scene differs')
            task = read(source/'task.json')
            if task.get('family') == 'mosaic' and task['scale']['scene_revision'] not in MOSAIC_DISPLAY_REVISIONS:
                raise ValueError('Unsupported Mosaic display revision: '+str(task['scale']['scene_revision']))
            for name, checksum in edit.get('input_evidence_sha256', {}).items():
                if name not in ('actions.json', 'process.jsonl') or digest(Path(spec['recording']).parent/name) != checksum:
                    raise ValueError('Station semantic evidence differs')
            for view in ('front', 'side'):
                if spec['id']+'--'+view not in camera_ids:
                    raise ValueError('Missing station camera: ' + spec['id']+'--'+view)
    return dict(status='verified', files=len(files), stations=len(ids),
                bundle_sha256=digest(root/'bundle.json'), scope=manifest['scope'],
                verification_scope='full_bundle' if cases is None else 'selected_render_dependencies')


def export(output, scene, release, cameras, asset, source_root):
    """Freeze required inputs, preserving source/edit bytes and deduplicating assets."""
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Choose a new bundle output')
    output.parent.mkdir(parents=True, exist_ok=True)
    source_root = Path(source_root).resolve()
    scene, asset = Path(scene).resolve(), Path(asset).resolve()
    release = deepcopy(read(release))
    # Runtime input paths are retained below; unrelated GPT/private/historical paths
    # are not dependencies of this presentation and must not leak into the bundle.
    release = {key:release[key] for key in ('schema', 'presentation', 'families')}
    for family in release['families'].values():
        for key in list(family):
            if key not in ('speedup', 'fps', 'oracle'):
                del family[key]
        for spec in family['oracle']:
            for key in list(spec):
                if key.startswith('historical_'):
                    del spec[key]
    with tempfile.TemporaryDirectory(prefix='.factory-export-', dir=output.parent) as temporary:
        folder = Path(temporary)/'data'
        folder.mkdir()
        content, directories = {}, {}
        def copy_file(src, dst):
            src, dst = Path(src), Path(dst)
            if src.is_symlink() or not src.is_file():
                raise ValueError('Only regular source files may be packaged: ' + str(src))
            sha = digest(src)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if sha in content:
                os.link(content[sha], dst)
            else:
                shutil.copyfile(src, dst)
                content[sha] = dst
        def copy_tree(src, dst):
            if not src.is_dir() or src.is_symlink():
                raise ValueError('Missing regular input directory: ' + str(src))
            for item in sorted(src.rglob('*')):
                if item.is_symlink():
                    raise ValueError('Symlinked source data: ' + str(item))
                if item.is_file():
                    if item.name.startswith('.env') or item.name in ('auth.json', 'runtime.sqlite'):
                        raise ValueError('Private runtime data in factory input: ' + str(item))
                    copy_file(item, dst/item.relative_to(src))
        copy_tree(scene.parent, folder/'scene')
        copy_tree(asset, folder/'asset')
        copy_file(cameras, folder/'cameras.json')
        for name, family in release['families'].items():
            for spec in family['oracle']:
                for field in PATH_FIELDS:
                    if field not in spec:
                        continue
                    if field == 'recording':
                        from ..tasks.families import oracle_recording
                        original = oracle_recording(spec[field], source_root).resolve()
                    else:
                        original = (source_root/spec[field]).resolve()
                    directory = original.parent if field == 'edit' else original
                    # One copy per source folder, even when several display cases
                    # explicitly reuse one recording. Archive hardlinks share bytes.
                    if directory not in directories:
                        destination = f'inputs/{len(directories):03d}' + ('/motion' if field == 'recording' else '')
                        copy_tree(directory, folder/destination)
                        if field == 'recording':
                            edit = read((source_root/spec['edit']).resolve())
                            for name, checksum in edit.get('input_evidence_sha256', {}).items():
                                if name not in ('actions.json', 'process.jsonl') or digest(directory.parent/name) != checksum:
                                    raise ValueError('Station semantic evidence differs')
                                copy_file(directory.parent/name, (folder/destination).parent/name)
                        directories[directory] = destination
                    destination = directories[directory]
                    spec[field] = destination+'/'+original.name if field == 'edit' else destination
        write(folder/'release.json', release)
        # The offline Blender metadata's absolute source path is informational.
        # Bind it portably; source_scene_sha256 remains the original authority.
        metadata = read(folder/'asset/scene.json')
        metadata['source_scene'] = 'scene/'+scene.name
        # Detach a deduplicated inode before writing a changed file.
        (folder/'asset/scene.json').unlink()
        write(folder/'asset/scene.json', metadata)
        inventory = {p.relative_to(folder).as_posix():dict(bytes=p.stat().st_size,sha256=digest(p))
                     for p in sorted(folder.rglob('*')) if p.is_file()}
        write(folder/'bundle.json', dict(schema=SCHEMA, scene='scene/'+scene.name,
            asset='asset', cameras='cameras.json', release='release.json', files=inventory,
            mosaic_revisions=sorted({read(folder/spec['directory']/'task.json')['scale']['scene_revision']
                                     for spec in release['families'].get('mosaic', {}).get('oracle', [])}),
            scope='Offline recorded-state presentation. Derived display tasks retain recorded_case_id; no new execution or score qualification.'))
        result = verify(folder)
        folder.rename(output)
    return result


def pack(root, archive):
    root, archive = Path(root).resolve(), Path(archive).resolve()
    result = verify(root)
    if archive.exists() or archive.is_relative_to(root):
        raise ValueError('Choose a new archive outside the data root')
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(archive.name+'.partial')
    try:
        with tarfile.open(temporary, 'w:gz', compresslevel=6, dereference=False) as tar:
            # bundle.json precedes inputs; all hardlink targets are earlier members.
            for p in [root/'bundle.json', *sorted(p for p in root.rglob('*') if p.is_file() and p != root/'bundle.json')]:
                tar.add(p, arcname=p.relative_to(root).as_posix(), recursive=False)
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return dict(**result, archive=str(archive), archive_sha256=digest(archive), bytes=archive.stat().st_size)


def restore(archive, output, expected_sha256):
    archive, output = Path(archive).resolve(), Path(output).resolve()
    if digest(archive) != expected_sha256:
        raise ValueError('Factory archive SHA-256 mismatch')
    if output.exists():
        return verify(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.factory-restore-', dir=output.parent) as temporary:
        folder = Path(temporary)/'data'
        folder.mkdir()
        seen = set()
        with tarfile.open(archive, 'r|gz') as tar:
            for member in tar:
                target = inside(folder, member.name)
                if member.name in seen:
                    raise ValueError('Duplicate archive entry')
                seen.add(member.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                if member.isfile():
                    with tar.extractfile(member) as src, target.open('xb') as dst:
                        shutil.copyfileobj(src, dst)
                elif member.islnk():
                    source = inside(folder, member.linkname)
                    if member.linkname not in seen or not source.is_file():
                        raise ValueError('Invalid archive hardlink')
                    os.link(source, target)
                else:
                    raise ValueError('Only regular files and prior internal hardlinks are allowed')
        result = verify(folder)
        folder.rename(output)
    return result


def setup(config, output, archive=None):
    config = read(config)
    output = Path(output).resolve()
    if output.exists():
        result = verify(output)
        if result['bundle_sha256'] != config['bundle_sha256']:
            raise ValueError('Existing data belongs to another factory release; choose another data root')
        return result
    if archive is not None:
        result = restore(archive, output, config['archive_sha256'])
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.factory-download-', dir=output.parent) as temporary:
            download = Path(temporary)/'factory.tar.gz'
            parts=config.get('parts') or [dict(url=config['url'],sha256=config['archive_sha256'])]
            with download.open('xb') as dst:
                for i,part in enumerate(parts):
                    local=Path(temporary)/'part'
                    for attempt in range(4):
                        try:
                            with urllib.request.urlopen(part['url'], timeout=90) as src, local.open('wb') as stream:
                                shutil.copyfileobj(src, stream, length=1024*1024)
                            if digest(local)!=part['sha256'] or ('bytes' in part and local.stat().st_size!=part['bytes']):
                                raise ValueError('Factory download part checksum mismatch')
                            break
                        except (OSError,ValueError):
                            local.unlink(missing_ok=True)
                            if attempt==3:raise
                            time.sleep(2**attempt)
                    with local.open('rb') as src:shutil.copyfileobj(src,dst,length=1024*1024)
                    local.unlink()
            result = restore(download, output, config['archive_sha256'])
    if result['bundle_sha256'] != config['bundle_sha256']:
        raise ValueError('Restored bundle differs from the pinned release')
    return result


def split_archive(archive, bundle_root, url_prefix, part_bytes=900*1024*1024):
    """GitHub assets have per-file limits; parts reconstruct the exact archive."""
    archive=Path(archive).resolve()
    if part_bytes<=0:
        raise ValueError('Positive archive part size required')
    parts=[]
    with archive.open('rb') as src:
        index=0
        while True:
            first=src.read(min(part_bytes,1024*1024))
            if not first:break
            path=archive.with_name(archive.name+f'.part{index:03d}')
            if path.exists():raise FileExistsError('Preserve existing archive part: '+str(path))
            with path.open('xb') as dst:
                dst.write(first);left=part_bytes-len(first)
                while left:
                    block=src.read(min(left,1024*1024))
                    if not block:break
                    dst.write(block);left-=len(block)
            parts.append(dict(url=url_prefix.rstrip('/')+'/'+path.name,sha256=digest(path),bytes=path.stat().st_size))
            index+=1
    return dict(schema='robofrontier.factory-download.v1',bundle_sha256=digest(Path(bundle_root)/'bundle.json'),
        archive_sha256=digest(archive),archive_bytes=archive.stat().st_size,parts=parts,
        scope='Mosaic R14 factory presentation; frozen source physics and qualifications are preserved')
