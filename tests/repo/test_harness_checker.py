"""A local machine's files must not make broken handoff links appear valid."""
from pathlib import Path
import tempfile
import unittest

from scripts.check_harness import documentation_links


class DocumentationLinkTests(unittest.TestCase):
    def test_relative_encoded_links_and_external_sources_remain_portable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            (root/'docs').mkdir()
            (root/'docs/other file.md').write_text('Target')
            page=root/'docs/index.md'
            page.write_text('[local](other%20file.md#section) [anchor](#section) '
                '[source](https://example.test/doc) [mail](mailto:example@example.test)')
            self.assertEqual(documentation_links(root,[page]),[])

    def test_existing_absolute_outside_and_symlink_targets_are_not_handoff_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent=Path(temporary).resolve()
            root=parent/'repo';root.mkdir()
            local=root/'local.md';local.write_text('Exists')
            external=parent/'external.md';external.write_text('Exists only outside checkout')
            (root/'external-link.md').symlink_to(external)
            page=root/'README.md'
            targets=[str(local),str(external),'../external.md','external-link.md','missing.md']
            page.write_text('\n'.join(f'[target]({target})' for target in targets))
            failures=documentation_links(root,[page])
            self.assertEqual([item['target'] for item in failures],targets)
            self.assertEqual(failures[-1]['reason'],'Local link target does not exist')


if __name__=='__main__':unittest.main()
