"""Download only the official Panda model and its referenced meshes.

Without vendor/panda/SOURCE.json it fetches the commit pinned in
configs/suites/cube_transport_cylinders/manifest.json (robot_source) and checks
every file against the pinned hashes before writing; --commit fetches another
commit explicitly. `.venv/bin/python -m robofrontier.cli bootstrap` restores the
same pinned Panda from the asset release.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "vendor" / "panda"
PINNED = ROOT / "configs/suites/cube_transport_cylinders/manifest.json"
REPO = "google-deepmind/mujoco_menagerie"


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "RoboFrontier-mini"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def download(commit):
    base = f"https://raw.githubusercontent.com/{REPO}/{commit}/franka_emika_panda"
    xml = get(f"{base}/panda.xml")
    tree = ET.fromstring(xml)
    meshes = sorted({node.attrib["file"] for node in tree.findall("asset/mesh")})
    files = {"panda.xml": xml}

    def fetch(name):
        path = f"assets/{name}"
        return path, get(f"{base}/{path}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for path, content in pool.map(fetch, meshes):
            files[path] = content
    for name in ("LICENSE", "README.md"):
        files[name] = get(f"{base}/{name}")
    return files, len(meshes)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", help="Fetch this menagerie commit instead of the pinned one (no hash check)")
    args = parser.parse_args(argv)
    manifest = DEST / "SOURCE.json"
    expected = None
    if args.commit:
        commit = args.commit
    elif manifest.exists():
        source = json.loads(manifest.read_text())
        if all((DEST / name).exists() and hashlib.sha256((DEST / name).read_bytes()).hexdigest() == digest
               for name, digest in source["sha256"].items()):
            print(f"Panda assets verified ({source['commit'][:12]})")
            return
        commit, expected = source["commit"], source["sha256"]
    else:
        pinned = json.loads(PINNED.read_text())["robot_source"]
        commit, expected = pinned["commit"], pinned["sha256"]
    files, meshes = download(commit)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    if expected is not None and hashes != expected:
        changed = sorted(set(hashes) ^ set(expected) | {n for n in set(hashes) & set(expected) if hashes[n] != expected[n]})
        raise SystemExit(f"Downloaded Panda files differ from the pinned hashes at {commit}: {changed}; nothing was written")
    (DEST / "assets").mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        (DEST / path).write_bytes(content)
    manifest.write_text(json.dumps({"repository": f"https://github.com/{REPO}", "commit": commit, "sha256": hashes},
                                   indent=2) + "\n")
    print(f"Downloaded Panda and {meshes} meshes ({sum(map(len, files.values())) / 1e6:.1f} MB), commit {commit}")


if __name__ == "__main__":
    main()
