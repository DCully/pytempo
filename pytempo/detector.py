import time
import statistics

from threading import Thread
from collections import deque, defaultdict
from queue import Queue

import numpy


class TempoDetector(object):

    def __init__(self, publisher):
        self._in_queue = Queue(maxsize=1024)
        self._publisher = publisher
        self._energy_hist_per_freq_band = []
        for _ in range(32):
            self._energy_hist_per_freq_band.append(deque(maxlen=43))
        self._beat_history = deque(maxlen=43*7)  # ~7 seconds
        # self._beat_histories = []
        # for _ in range(32):
        #     self._beat_histories.append(deque(maxlen=43*7))
        self._processing_thread = Thread(
            target= self._run_data_processing,
            daemon=True,
        )
        self._processing_thread.start()

    def _gap_to_bpm(self, gap_length):
        return (1 / (gap_length / 43)) * 60.0

    def _bpm_to_gap(self, bpm):
        # convert beats/minute to beats/second (divide by 60)
        bps = bpm / 60.0
        # convert beats/second to seconds/beat (flip)
        spb = 1.0 / bps
        # seconds/beat * 43 gap / sec == gap / beat
        return int(spb * 43)

    def _detect_tempo(self):
        """
        Look at the beat history and derive a tempo, returning
        a BPM as an int if one is found (None otherwise).
        """

        # wait for a full history before inspecting it
        if not len(self._beat_history) == 43*7:
            return

        # a gap of 19 is about 136 bpm, and a gap of 35 is about 73 bpm
        # By staying inside these possible bpm values, we avoid
        # issues with BPM doubling/halving (i.e., missing a beat and counting some
        # votes for 60 BPM instead of 120 BPM, skewing our final result downwards)
        # songs outside of this range are rare anyway (at least in popular music)

        # count all relevant gaps
        gap_length_counts = defaultdict(lambda: 0)
        for gap_length in range(19, 35):
            for start in range(0, len(self._beat_history) - gap_length):
                end = start + gap_length
                if self._beat_history[start] is True and self._beat_history[end] is True:
                    gap_length_counts[gap_length] += 1

        # convert each gap we found into a BPM value (one vote per gap)
        bpm_candidates = []
        for gap_length in gap_length_counts.keys():

            # discard BPM candidates for which we only noticed one interval
            if gap_length_counts[gap_length] < 2:
                continue

            for _ in range(gap_length_counts[gap_length]):
                bpm_candidates.append(self._gap_to_bpm(gap_length))

        # if there's not enough data to analyze just give up
        if len(bpm_candidates) < 2:
            return None

        # filter out BPM candidates that are more than 2 standard deviations
        # off of the original mean
        std_dev = statistics.stdev(bpm_candidates)
        mean = statistics.mean(bpm_candidates)
        filtered = [bpm for bpm in bpm_candidates if abs(mean - bpm) < std_dev]

        # if there's not enough data to analyze just give up (check filtered data)
        if len(filtered) < 2:
            return None

        # # dump out the beat histories across all 32 channels for visual inspection
        # if len(self._beat_histories[0]) == 43 * 7:
        #     for band_idx in range(32):
        #         my_str = ''
        #         for e in self._beat_histories[band_idx]:
        #             my_str += '1' if e else '0'
        #         print(my_str)
        #     print('\n\n')

        bpm = statistics.mean(filtered)

        if 71 < bpm < 139:
            return bpm
        return None

    def _detect_beat(self, data):
        """
        Process the raw data to detect beats in this instant, and update
        self._beat_history accordingly with a True or False value.
        """
        # collapse data into one channel
        data = [sum(d) / len(d) for d in data]

        # compute fft of samples (giving us 1024 complex numbers)
        data = numpy.fft.fft(data)

        # compute square of modulus of each sample
        # this gives us amplitudes per frequency
        ampls_per_freq = [d.real*d.real + d.imag*d.imag for d in data]

        # compute sub-band energies for this 'instant'
        inst_sub_band_energies = []
        for sub_band in range(32):
            sub_band_energy = 0
            for i in range(32):
                sub_band_energy += ampls_per_freq[sub_band*32 + i]
            # store the summed inst energy in this sub-band
            inst_sub_band_energies.append(sub_band_energy)

        # update sub-band energy histories to include this instant
        for i in range(len(inst_sub_band_energies)):
            self._energy_hist_per_freq_band[i].append(
                inst_sub_band_energies[i]
            )

        # if we have a complete sub-band energy history, compare
        # the values for this 'instant' to the trailing history
        this_inst_is_beat = False
        if len(self._energy_hist_per_freq_band[0]) == 43:

            # compute the average historical energy in the last
            # second, per frequency band
            avg_sub_band_energies = [
                sum(x) / 43 for x in self._energy_hist_per_freq_band
            ]

            # require finding beats in at least 3 bands for this to count
            for inst_nrg, nearby_nrg in zip(
                    inst_sub_band_energies, avg_sub_band_energies):
                if inst_nrg > nearby_nrg * 1.3:  # here be dragons
                    this_inst_is_beat = True

            # # record beats found across all 32 frequency bands
            # for band_idx in range(32):
            #     inst_nrg = inst_sub_band_energies[band_idx]
            #     avg_nrg = avg_sub_band_energies[band_idx]
            #     beat_found = False
            #     if inst_nrg > avg_nrg * 1.3:
            #         beat_found = True
            #     self._beat_histories[band_idx].append(beat_found)

        # update our trailing beat history deque
        self._beat_history.append(this_inst_is_beat)

    def _run_data_processing(self):
        """
        Threading target to continually read inputted data
        and process it in 1024-sample batches.
        """
        data = [0] * 1024
        idx = 0

        # count = 0
        # import time
        # start_ts = time.time()

        while True:
            data[idx] = self._in_queue.get()

            # count += 1

            if idx == 1023:
                self._detect_beat(data)
                bpm = self._detect_tempo()
                self._publisher.publish(bpm)
                idx = 0
            else:
                idx += 1

            # if count % 44100 == 0:
            #     print('processed {} seconds of data in '
            #           '{} seconds'
            #           .format(count / 44100,
            #                   time.time() - start_ts))

    def add_sample(self, sample):
        """
        Push an audio sample into the Detector's internal
        processing queue.

        Sample should be an iterable of one or more values,
        where each value is the sample value for a single
        audio channel.
        """
        self._in_queue.put(sample)
