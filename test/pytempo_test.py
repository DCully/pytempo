import os
import unittest

import numpy
import scipy.io.wavfile

from pytempo import TempoDetector


class PyTempoIntegrationTest(unittest.TestCase):
    # these tests use actual wav data, so they'll take a minute or two

    def test_85_click(self):
        self.validate(
            'click_85.wav',
            85,
        )

    def test_105_click(self):
        self.validate(
            'click_105.wav',
            105,
        )

    def test_120_click(self):
        self.validate(
            'click_120.wav',
            120,
        )

    def test_bgs(self):
        self.validate(
            'bgs.wav',
            103,
        )

    def test_gorillaz(self):
        self.validate(
            'gorillaz.wav',
            88,
        )

    def test_kesha(self):
        self.validate(
            'kesha.wav',
            120,
        )

    def test_stevie(self):
        self.validate(
            'stevie.wav',
            100,
        )

    def validate(self, wav_file_name, expected_bpm):
        results = []

        class Pub(object):
            def publish(self, a):
                if a is not None:
                    results.append(a)

        wav_file_path = os.path.abspath(os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            'pytempo_test_data',
            wav_file_name,
        ))
        detector = TempoDetector(
            Pub(),
            fft_impl=numpy.fft.fft,
        )
        _, data = scipy.io.wavfile.read(
            wav_file_path,
        )
        for sample in data:
            detector.add_sample(
                sample,
            )
        if expected_bpm is None:
            self.assertTrue(len(results) == 0)
        else:
            self.assertTrue(len(results) > 0)
            for result in results:
                self.assertTrue(
                    expected_bpm - 3 < result < expected_bpm + 3,
                    'reported BPM of {} more than 3 off '
                    'from expected BPM of {} in wav file named {}'
                    .format(result, expected_bpm, wav_file_name)
                )


if __name__ == "__main__":
    unittest.main()
