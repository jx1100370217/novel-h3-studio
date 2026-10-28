import unittest

from novel_h3.subtitle_audit import parse_tsv


TSV_HEADER = ('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t'
              'left\ttop\twidth\theight\tconf\ttext')


def row(word: str, conf: float) -> str:
    return f'5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t{conf}\t{word}'


class ParseTsvTests(unittest.TestCase):
    def test_keeps_confident_cjk(self):
        output = '\n'.join([TSV_HEADER, row('明天', 96.0), row('我', 57.9)])
        self.assertEqual(parse_tsv(output), [('明天', 96.0), ('我', 57.9)])

    def test_drops_low_confidence_and_latin(self):
        output = '\n'.join([TSV_HEADER, row('故人', 0.0), row('1', 72.0), row('天', 36.0)])
        self.assertEqual(parse_tsv(output), [])

    def test_ignores_malformed_rows(self):
        output = '\n'.join([TSV_HEADER, 'bad\trow', row('走', 88.0)])
        self.assertEqual(parse_tsv(output), [('走', 88.0)])


if __name__ == '__main__':
    unittest.main()
