"""Install the pinned Antigravity binary from Google's archive with SHA-512 verification."""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import tarfile
import tempfile
import urllib.request

VERSION = '1.5.7'
ROOT = 'https://storage.googleapis.com/antigravity-public/antigravity-cli/1.5.7-6190022064472064/'
ARCHIVES = {
    ('Darwin', 'arm64'): ('darwin-arm/cli_mac_arm64.tar.gz', 'c9746409083a9b15c217757aa2ef399ee7d4398602a30038583ea45196fc27d1662745341e45a116c07be19c08587de1e5929e365d2a46aea385fa33f0c2396a'),
    ('Linux', 'x86_64'): ('linux-x64/cli_linux_x64.tar.gz', '60bca280414ed11723f58b3b671962ae394cc2d0c25e3f58e32e1c6847c978cbc77ec6f40e7f3992001c399d80aeb8b64c9ec892abddd591b12413c5ee6d9fce'),
    ('Linux', 'aarch64'): ('linux-arm/cli_linux_arm64.tar.gz', 'bebd69ad1713414b82e370aec6be0e678a413332bf3c835d9ba22e4befff040b6c74e1bf974fd83ebc4c733ed6e37d2bdc1caae58027c2b326dd04d630bfebb1'),
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
