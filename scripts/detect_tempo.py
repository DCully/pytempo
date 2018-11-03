import argparse

import scipy.io.wavfile

from pytempo import TempoDetector
from pytempo import PrintPublisher


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument(
        "-i", "--input-wav-file",
        dest="wav_file",
    )
    return p.parse_args()


def main(args):
    rate, data = scipy.io.wavfile.read(
        args.wav_file,
    )
    if rate != 44100:
        raise Exception('Wav file must be 44100Hz')
    detector = TempoDetector(
        PrintPublisher(),
    )
    for sample in data:  # seven seconds
        detector.add_sample(
            sample,
        )


if __name__ == "__main__":
    main(parse_args())
