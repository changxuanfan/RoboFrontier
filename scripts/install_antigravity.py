"""Install the pinned Antigravity binary from Google's archive with SHA-512 verification."""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import tarfile
import tempfile
import urllib.request

VERSION = '1.5.5'
ROOT = 'https://storage.googleapis.com/antigravity-public/antigravity-cli/1.5.5-6740358537805824/'
ARCHIVES = {
    ('Darwin', 'arm64'): ('darwin-arm/cli_mac_arm64.tar.gz', 'ca6424867a4527698e54b805c2456605b905a49ffc9b664ae2ee0fd4510fcd7b82d9721b2622a1d46048156a44431dc894359177fae44207363c8c878687b647'),
    ('Linux', 'x86_64'): ('linux-x64/cli_linux_x64.tar.gz', '746a2bd73f83b65d9b44f2fc55d0f0f511ff7f89702846213eeabd76d06bc9c98576b424c2babc7b947f15e518447b946ba02dca260b778363c55c07a7f7a277'),
    ('Linux', 'aarch64'): ('linux-arm/cli_linux_arm64.tar.gz', 'eb3e025c125c1c60a1493a0c1d9cdf15e8372277d6d3b015e8d29e1bd095344eece5cbc2447f238148bd259d5f2daa0f75641adc0ac02b5fad57edc4ed842d59'),
}


def install(output):
    output = Path(output).expanduser().absolute()
    if output.exists():
        raise ValueError('Choose a new installation path; an existing CLI is never overwritten')
    key = platform.system(), platform.machine()
    if key not in ARCHIVES:
        raise ValueError('No verified Antigravity archive for this platform')
    relative, expected = ARCHIVES[key]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rf-agy-install-', dir=output.parent) as folder:
        archive = Path(folder)/'archive.tar.gz'
        with urllib.request.urlopen(ROOT+relative, timeout=120) as source, archive.open('wb') as target:
            while block := source.read(1024*1024):
                target.write(block)
        with archive.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha512').hexdigest() != expected:
                raise ValueError('Antigravity archive SHA-512 mismatch')
        with tarfile.open(archive, 'r:gz') as bundle:
            member = bundle.getmember('antigravity')
            if not member.isfile():
                raise ValueError('Expected the regular Antigravity executable')
            with bundle.extractfile(member) as source, output.open('xb') as target:
                while block := source.read(1024*1024):
                    target.write(block)
        output.chmod(0o755)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path.home()/'.local/bin/agy')
    print(install(parser.parse_args().output))
