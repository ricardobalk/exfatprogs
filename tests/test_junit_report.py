#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import junit_report


class JunitReportTests(unittest.TestCase):
    def test_describes_passes_failures_and_skips(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = root / 'images'
            images.mkdir()
            (images / 'results.json').write_text(json.dumps({
                'status': 'FAIL',
                'tests': [
                    {'case': 'model', 'seed': 7, 'iterations': 5000, 'sector': 512,
                     'cluster': 4096, 'status': 'PASS', 'seconds': 1.25},
                    {'case': 'fault', 'direction': 'shrink', 'mode': 'kill',
                     'position': 9, 'event': 'source.write', 'status': 'FAIL',
                     'error': 'image hash changed'},
                    {'case': 'driver', 'status': 'NOT_RUN', 'reason': 'CAP_SYS_ADMIN missing'},
                ],
            }))
            output, summary = root / 'junit.xml', root / 'summary.md'
            junit_report.generate('resize', [root], output, summary)

            xml = ET.parse(output).getroot()
            cases = xml.findall('.//testcase')
            self.assertEqual(3, len(cases))
            self.assertIn('seed 7', cases[0].attrib['name'])
            failure = xml.find('.//failure')
            self.assertIn('What:', failure.text)
            self.assertIn('Why:', failure.text)
            self.assertIn('Where:', failure.text)
            self.assertEqual(1, len(xml.findall('.//skipped')))
            text = summary.read_text()
            self.assertIn('| What | Why | Where | If it failed |', text)
            self.assertIn('Seeded grow and shrink image preservation', text)
            self.assertEqual('layout gpt', junit_report.case_name({'layout': 'gpt'}))

    def test_prefers_combined_case_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / 'model'
            child = model / '0'
            child.mkdir(parents=True)
            (model / 'results.json').write_text(json.dumps({'status': 'PASS', 'completed': 1}))
            (model / 'cases.jsonl').write_text(json.dumps({'seed': 4, 'status': 'PASS'}) + '\n')
            (child / 'results.json').write_text(json.dumps({'status': 'PASS', 'completed': 1}))
            (child / 'cases.jsonl').write_text(json.dumps({'seed': 4, 'status': 'PASS'}) + '\n')
            output = root / 'junit.xml'
            junit_report.generate('defrag', [root], output)
            self.assertEqual(1, len(ET.parse(output).findall('.//testcase')))

    def test_missing_results_is_a_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'junit.xml'
            junit_report.generate('resize', [root / 'missing'], output)
            failure = ET.parse(output).find('.//failure')
            self.assertIsNotNone(failure)
            self.assertIn('No results.json', failure.text)


if __name__ == '__main__':
    unittest.main()
