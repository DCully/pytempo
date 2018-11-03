import time
import statistics

from threading import Thread
from collections import deque
from queue import Queue

import numpy


class TempoDetector(object):

    def __init__(self, publisher):
        self._in_queue = Queue(maxsize=1024)
        self._publisher = publisher
        self._energy_hist_per_freq_band = [deque(maxlen=43)] * 32
        self._beat_history = deque(maxlen=43*7)  # ~7 seconds
        self._processing_thread = Thread(
            target= self._run_data_processing,
            daemon=True,
        )
        self._processing_thread.start()

    def _estimate_bpm_from(self, history):
        last = None
        gaps = []
        for idx in range(len(history)):
            was_beat = history[idx]
            if was_beat:
                if last is None:
                    last = idx
                else:
                    gap = idx - last
                    # a gap of 10 is 4 bps or 240 bpm
                    # a gap of 45 is <1 bps or <60 bpm
                    if 10 < gap < 45:
                        # this gap is a reasonable size
                        gaps.append(gap)
                        last = idx
        bpms_from_gaps = [(1 / (x / 43)) * 60.0 for x in gaps]
        print(bpms_from_gaps)
        if len(bpms_from_gaps) < 1:
            return None
        bpm = statistics.harmonic_mean(bpms_from_gaps)
        print(bpm)
        return bpm

    def _detect_tempo(self):
        """
        Look at the beat history and derive a tempo, publishing
        the tempo (a BPM) as an int if one is found (do not publish
        if you do not find a convincing tempo).
        """

        # wait for a full history before inspecting it
        if not len(self._beat_history) == 43*7:
            return

        # compute tempo from smoothed beats
        # TODO - this is naive - apply a list of BPM templates
        bpm = self._estimate_bpm_from(self._beat_history)
        if bpm is None or 70 < bpm < 150:
            return None
        return bpm

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

            # require finding beats in at least 2 bands for this to count
            beat_bands_count = 0
            for inst_nrg, nearby_nrg in zip(
                    inst_sub_band_energies, avg_sub_band_energies):
                if inst_nrg > nearby_nrg * 1.2:
                    beat_bands_count += 1
            if beat_bands_count > 3:
                this_inst_is_beat = True

        # update our trailing beat history deque
        self._beat_history.append(this_inst_is_beat)

    def _run_data_processing(self):
        """
        Threading target to continually read inputted data
        and process it in 1024-sample batches.
        """
        data = [0] * 1024
        idx = 0
        while True:
            data[idx] = self._in_queue.get()
            if idx == 1023:
                self._detect_beat(data)
                self._detect_tempo()
                idx = 0
            else:
                idx += 1

    def add_sample(self, sample):
        """
        Push an audio sample into the Detector's internal
        processing queue.

        Sample should be an iterable of one or more values,
        where each value is the sample value for a single
        audio channel.
        """
        self._in_queue.put(sample)
