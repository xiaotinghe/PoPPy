"""
This script contains a parent class of data preprocess functions and classes
The operations include:
1) random or feature-based stitching
2) random or feature-based superposition
3) aggregation (i.e., convert event sequences to time series, which contains the number of events in each time interval)
4) minbatching

The data in our toolbox is always formulated as follows:

database = {'event_features': None or (De, C) float array of event's static features,
                              C is the number of event types.
            'type2idx': a Dict = {'event_name': event_index}
            'idx2type': a Dict = {event_index: 'event_name'}
            'seq2idx': a Dict = {'seq_name': seq_index}
            'idx2seq': a Dict = {seq_index: 'seq_name'}
            'sequences': a List  = [seq_1, seq_2, ..., seq_N].
            }

For the i-th sequence:
seq_i = {'times': (N,) float array of timestamps, N is the number of events.
         'events': (N,) int array of event types.
         'seq_feature': None or (Ds,) float array of sequence's static feature.
         't_start': a float number indicating the start timestamp of the sequence.
         't_stop': a float number indicating the stop timestamp of the sequence.
         'label': None or int/float number indicating the labels of the sequence
         }

Note that for stitching and superposition operation, the two database should with same event types and event features.
The seq_idx and seq_name follows the first database.
The seq_feature is the average of those of two stitched/superposed sequences.
"""

import copy
from dev.util import logger
import time
import torch
import numpy as np
from torch.utils.data import Dataset
from typing import Dict


def stitching(database1: Dict, database2: Dict, method: str ='random') -> Dict:
    """
    Stitch each sequence in database2 to the end of one sequence of database1
    :param database1: the observed event sequences
    :param database2: another observed event sequences
        database = {'event_features': None or (De, C) float array of event's static features,
                                  C is the number of event types.
                    'type2idx': a Dict = {'event_name': event_index}
                    'idx2type': a Dict = {event_index: 'event_name'}
                    'seq2idx': a Dict = {'seq_name': seq_index}
                    'idx2seq': a Dict = {seq_index: 'seq_name'}
                    'sequences': a List  = {seq_1, seq_2, ..., seq_N}.
                    }

        For the i-th sequence:
        seq_i = {'times': (N,) float array of timestamps, N is the number of events.
                 'events': (N,) int array of event types.
                 'seq_feature': None or (Ds,) float array of sequence's static feature.
                 't_start': a float number indicating the start timestamp of the sequence.
                 't_stop': a float number indicating the stop timestamp of the sequence.
                 'label': None or int/float number indicating the labels of the sequence}

    :param method: a string indicates stitching method:
        "random": stitch the seq_j in sequences2 to the seq_i in sequences1 for j ~ {1,...,N}, i=1,...,N and
                  time-shifting is applied to sequences2.
                  This method is suitable for the sequences generated by a same stationary point process.

        "feature": stitch the seq_j in sequences2 to the seq_i in sequences1 for j ~{1,...,N}, i=1,...,N and
                   j is sampled according to the similarity between two sequences.
                   The similarity is calculated by the Gaussian kernel of seq_features, labels and times.
                   When seq_features/labels are not available, only timestamp information are taken into account.

    :return:
        the output sequences are with the same format as database1.
    """
    start = time.time()
    output = copy.deepcopy(database1)
    if database1['type2idx'] == database2['type2idx']:
        if method is None or method == 'random':
            logger.info('random stitching is applied...')
            index = np.random.permutation(len(database2['sequences']))  # random permutation of the index of sequences

            for i in range(len(database1['sequences'])):
                seq_i = database1['sequences'][i]
                j = i % len(database2['sequences'])
                seq_j = database2['sequences'][index[j]]

                # concatenate two timestamp arrays with time shifting
                times1 = seq_i['times']
                times2 = seq_j['times'] - seq_j['t_start'] + seq_i['t_stop']
                output['sequences'][i]['times'] = np.concatenate((times1, times2), axis=0)

                # concatenate two event arrays
                output['sequences'][i]['events'] = np.concatenate((seq_i['events'], seq_j['events']), axis=0)

                # update stop timestamp
                output['sequences'][i]['t_stop'] = seq_i['t_stop'] + seq_j['t_stop'] - seq_j['t_start']

                # update features
                if seq_i['seq_feature'] is not None and seq_j['seq_feature'] is not None:
                    output['sequences'][i]['seq_feature'] = (seq_i['seq_feature'] + seq_j['seq_feature'])/2

                if i % 1000 == 0:
                    logger.info('{} sequences have been stitched... Time={}ms.'.format(
                        i, round(1000*(time.time() - start))))

        elif method == 'feature':
            logger.info('feature-based stitching is applied...')

            for i in range(len(database1['sequences'])):
                prob = np.zeros((len(database2['sequences']),))
                seq_i = database1['sequences'][i]

                for j in range(len(database2['sequences'])):
                    seq_j = database2['sequences'][j]

                    if seq_j['t_start'] > seq_i['t_stop']:
                        # consider temporal order
                        weight = np.exp(-(seq_j['t_start'] - seq_i['t_stop']) ** 2)
                        # consider feature similarity
                        if seq_i['seq_feature'] is not None and seq_j['seq_feature'] is not None:
                            weight *= np.exp(-np.linalg.norm(seq_i['seq_feature'] - seq_j['seq_feature']) ** 2)
                        # consider label consistency
                        if seq_i['label'] is not None and seq_j['label'] is not None:
                            if seq_i['label'] != seq_j['label']:
                                weight = 0
                    else:
                        weight = 0

                    prob[j] = weight

                # sampling a sequence from database2
                if np.sum(prob) > 0:
                    prob = prob/np.sum(prob)
                else:
                    prob = np.ones((len(database2['sequences']),))/len(database2['sequences'])

                j = np.random.choice(len(database2['sequences']), p=prob)
                seq_j = database2['sequences'][j]

                # concatenate two timestamp arrays with time shifting
                times1 = seq_i['times']
                times2 = seq_j['times'] - seq_j['t_start'] + seq_i['t_stop']
                output['sequences'][i]['times'] = np.concatenate((times1, times2), axis=0)

                # concatenate two event arrays
                output['sequences'][i]['events'] = np.concatenate((seq_i['events'], seq_j['events']), axis=0)

                # update stop timestamp
                output['sequences'][i]['t_stop'] = seq_i['t_stop'] + seq_j['t_stop'] - seq_j['t_start']

                # update features
                if seq_i['seq_feature'] is not None and seq_j['seq_feature'] is not None:
                    output['sequences'][i]['seq_feature'] = (seq_i['seq_feature'] + seq_j['seq_feature']) / 2

                if i % 1000 == 0:
                    logger.info('{} sequences have been stitched... Time={}ms.'.format(
                        i, round(1000*(time.time() - start))))
        else:
            logger.warning('You need to define your own stitching method... '
                           'The function returns the first database.')
    else:
        logger.warning('The two databases do not have the same event types... '
                       'The function returns the first database.')

    return output


def superposing(database1: Dict, database2: Dict, method: str ='random') -> Dict:
    """
    Superpose each sequence in database2 to one sequence of database1
    :param database1: the observed event sequences
    :param database2: another observed event sequences
        database = {'event_features': None or (C, De) float array of event's static features,
                                  C is the number of event types.
                    'type2idx': a Dict = {'event_name': event_index}
                    'idx2type': a Dict = {event_index: 'event_name'}
                    'seq2idx': a Dict = {'seq_name': seq_index}
                    'idx2seq': a Dict = {seq_index: 'seq_name'}
                    'sequences': a List  = {seq_1, seq_2, ..., seq_N}.
                    }

        For the i-th sequence:
        seq_i = {'times': (N,) float array of timestamps, N is the number of events.
                 'events': (N,) int array of event types.
                 'seq_feature': None or (Ds,) float array of sequence's static feature.
                 't_start': a float number indicating the start timestamp of the sequence.
                 't_stop': a float number indicating the stop timestamp of the sequence.
                 'label': None or int/float number indicating the labels of the sequence}

    :param method: a string indicates superposing method:
        "random": superpose the seq_j in sequences2 to the seq_i in sequences1 for j ~ {1,...,N}, i=1,...,N and
                  time-shifting is applied to sequences2.
                  This method is suitable for the sequences generated by a same stationary point process.

        "feature": superpose the seq_j in sequences2 to the seq_i in sequences1 for j ~{1,...,N}, i=1,...,N and
                   j is sampled according to the similarity between two sequences.
                   The similarity is calculated by the Gaussian kernel of seq_features, labels and times.
                   When seq_features/labels are not available, only timestamp information are taken into account.

                   Different from stitching operation, to enlarge the power of superposition,
                   the sequences with large dissimilarity are more likely to be superposed together

    :return:
        the output sequences are with the same format as database1.
    """
    start = time.time()
    output = copy.deepcopy(database1)
    if database1['type2idx'] == database2['type2idx']:
        if method is None or method == 'random':
            logger.info('random superposition is applied...')
            index = np.random.permutation(len(database2['sequences']))  # random permutation of the index of sequences

            for i in range(len(database1['sequences'])):
                seq_i = database1['sequences'][i]
                j = i % len(database2['sequences'])
                seq_j = database2['sequences'][index[j]]

                # concatenate two timestamp arrays and sort the concatenate result
                times1 = seq_i['times']
                times2 = seq_j['times']
                output['sequences'][i]['times'] = np.concatenate((times1, times2), axis=0)
                order = np.argsort(output['sequences'][i]['times'])
                output['sequences'][i]['times'] = output['sequences'][i]['times'][order]

                # concatenate two event arrays and sort them according to the order of time
                output['sequences'][i]['events'] = np.concatenate((seq_i['events'], seq_j['events']), axis=0)
                output['sequences'][i]['events'] = output['sequences'][i]['events'][order]

                # update stop and start timestamp
                output['sequences'][i]['t_start'] = min([seq_i['t_start'], seq_j['t_stop']])
                output['sequences'][i]['t_stop'] = max([seq_i['t_stop'], seq_j['t_stop']])

                # update features
                if seq_i['seq_feature'] is not None and seq_j['seq_feature'] is not None:
                    output['sequences'][i]['seq_feature'] = (seq_i['seq_feature'] + seq_j['seq_feature']) / 2

                if i % 1000 == 0:
                    logger.info('{} sequences have been superposed... Time={}ms.'.format(
                        i, round(1000*(time.time() - start))))

        elif method == 'feature':
            logger.info('feature-based superposition is applied...')

            for i in range(len(database1['sequences'])):
                prob = np.zeros((len(database2['sequences']),))
                seq_i = database1['sequences'][i]

                for j in range(len(database2['sequences'])):
                    seq_j = database2['sequences'][j]

                    if seq_j['t_start'] > seq_i['t_stop']:
                        # consider temporal order
                        weight = np.exp(-(seq_j['t_start'] - seq_i['t_stop']) ** 2)
                        # consider feature similarity
                        if seq_i['seq_feature'] is not None and seq_j['seq_feature'] is not None:
                            weight *= np.exp(-np.linalg.norm(seq_i['seq_feature'] - seq_j['seq_feature']) ** 2)
                        # consider label consistency
                        if seq_i['label'] is not None and seq_j['label'] is not None:
                            if seq_i['label'] != seq_j['label']:
                                weight = 0
                    else:
                        weight = 0

                    prob[j] = weight

                # sampling a sequence from database2
                if np.sum(prob) > 0:
                    prob = prob/np.sum(prob)
                else:
                    prob = np.ones((len(database2['sequences']),))/len(database2['sequences'])

                j = np.random.choice(len(database2['sequences']), p=prob)
                seq_j = database2['sequences'][j]

                # concatenate two timestamp arrays and sort the concatenate result
                times1 = seq_i['times']
                times2 = seq_j['times']
                output['sequences'][i]['times'] = np.concatenate((times1, times2), axis=0)
                order = np.argsort(output['sequences'][i]['times'])
                output['sequences'][i]['times'] = output['sequences'][i]['times'][order]

                # concatenate two event arrays and sort them according to the order of time
                output['sequences'][i]['events'] = np.concatenate((seq_i['events'], seq_j['events']), axis=0)
                output['sequences'][i]['events'] = output['sequences'][i]['events'][order]

                # update stop and start timestamp
                output['sequences'][i]['t_start'] = min([seq_i['t_start'], seq_j['t_stop']])
                output['sequences'][i]['t_stop'] = max([seq_i['t_stop'], seq_j['t_stop']])

                # update features
                if seq_i['seq_feature'] is not None and seq_j['seq_feature'] is not None:
                    output['sequences'][i]['seq_feature'] = (seq_i['seq_feature'] + seq_j['seq_feature']) / 2

                if i % 1000 == 0:
                    logger.info('{} sequences have been stitched... Time={}ms.'.format(
                        i, round(1000*(time.time() - start))))
        else:
            logger.warning('You need to define your own superposition method... '
                           'The function returns the first database.')
    else:
        logger.warning('The two databases do not have the same event types... '
                       'The function returns the first database.')

    return output


def aggregating(database, dt):
    """
    Count the number of events in predefined time bins,
    and convert event sequences to aggregate time series
    :param database: the observed event sequences
    :param dt: a float number indicating the length of time bin.
    :return:
        the output's format is shown as follows:

          output = {'event_features': None or (De, C) float array of event's static features,
                              C is the number of event types.
                    'type2idx': a Dict = {'event_name': event_index}
                    'idx2type': a Dict = {event_index: 'event_name'}
                    'seq2idx': a Dict = {'seq_name': seq_index}
                    'idx2seq': a Dict = {seq_index: 'seq_name'}
                    'sequences': a List  = {seq_1, seq_2, ..., seq_N}.
                    }

        For the i-th sequence:
        seq_i = {'times': (N,) float array of discrete timestamps,
                          N = [(t_stop - t_start)/dt] is the number of bins.
                 'events': (N, C) int array of event types,
                           events[n, c] counts the number of type-c events in the n-th bin
                 'seq_feature': None or (Ds,) float array of sequence's static feature.
                 't_start': a float number indicating the start timestamp of the sequence.
                 't_stop': a float number indicating the stop timestamp of the sequence.
                 'label': None or int/float number indicating the labels of the sequence}
    """
    start = time.time()
    output = copy.deepcopy(database)
    num_types = len(database['type2idx'])
    logger.info('aggregation of event sequences is applied...')

    for i in range(len(database['sequences'])):
        seq_i = database['sequences'][i]
        num_bins = round((seq_i['t_stop'] - seq_i['t_start'])/dt) + 1
        times = np.zeros((num_bins,))
        events = np.zeros((num_bins, num_types))

        for n in range(num_bins):
            times[n] = seq_i['t_start'] + (n+1)*dt

        for k in range(seq_i['times'].shape[0]):
            n = int(round((seq_i['times'][k] - seq_i['t_start'])/dt))
            c = seq_i['events'][k]
            events[n, c] += 1

        output['sequences'][i]['times'] = times
        output['sequences'][i]['events'] = events

        if i % 1000 == 0:
            logger.info('{} sequences have been aggregated... Time={}ms.'.format(
                i, round(1000 * (time.time() - start))))

    return output


class EventSampler(Dataset):
    """Load event sequences via minbatch"""
    def __init__(self, database, memorysize):
        """
        :param database: the observed event sequences
            database = {'event_features': None or (C, De) float array of event's static features,
                                      C is the number of event types.
                        'type2idx': a Dict = {'event_name': event_index}
                        'idx2type': a Dict = {event_index: 'event_name'}
                        'seq2idx': a Dict = {'seq_name': seq_index}
                        'idx2seq': a Dict = {seq_index: 'seq_name'}
                        'sequences': a List  = {seq_1, seq_2, ..., seq_N}.
                        }

            For the i-th sequence:
            seq_i = {'times': (N,) float array of timestamps, N is the number of events.
                     'events': (N,) int array of event types.
                     'seq_feature': None or (Ds,) float array of sequence's static feature.
                     't_start': a float number indicating the start timestamp of the sequence.
                     't_stop': a float number indicating the stop timestamp of the sequence.
                     'label': None or int/float number indicating the labels of the sequence}
        :param memorysize: how many historical events remembered by each event
        """
        self.event_cell = []
        self.time_cell = []
        self.database = database
        self.memory_size = memorysize
        for i in range(len(database['sequences'])):
            seq_i = database['sequences'][i]
            times = seq_i['times']
            events = seq_i['events']
            t_start = seq_i['t_start']
            for j in range(len(events)):
                target = events[j]
                # former = np.zeros((memorysize,), dtype=np.int)
                # former = np.random.permutation(len(self.database['type2idx']))
                # former = former[:memorysize]
                former = np.random.choice(len(self.database['type2idx']), memorysize)
                target_t = times[j]
                former_t = t_start * np.ones((memorysize,))

                if 0 < j < memorysize:
                    former[-j:] = events[:j]
                    former_t[-j:] = times[:j]
                elif j >= memorysize:
                    former = events[j-memorysize:j]
                    former_t = times[j-memorysize:j]

                self.event_cell.append((target, former, i))
                self.time_cell.append((target_t, former_t))
        logger.info('In this dataset, the number of events = {}.'.format(len(self.event_cell)))
        logger.info('Each event is influenced by its last {} historical events.'.format(self.memory_size))

    def __len__(self):
        return len(self.event_cell)

    def __getitem__(self, idx):
        current_time = torch.Tensor([self.time_cell[idx][0]])  # torch.from_numpy()
        current_time = current_time.type(torch.FloatTensor)
        history_time = torch.from_numpy(self.time_cell[idx][1])
        history_time = history_time.type(torch.FloatTensor)

        current_event_numpy = self.event_cell[idx][0]
        current_event = torch.Tensor([self.event_cell[idx][0]])
        current_event = current_event.type(torch.LongTensor)
        history_event_numpy = self.event_cell[idx][1]
        history_event = torch.from_numpy(self.event_cell[idx][1])
        history_event = history_event.type(torch.LongTensor)

        current_seq_numpy = self.event_cell[idx][2]
        current_seq = torch.Tensor([self.event_cell[idx][2]])
        current_seq = current_seq.type(torch.LongTensor)

        if self.database['sequences'][current_seq_numpy]['seq_feature'] is None \
                and self.database['event_features'] is None:
            return current_time, history_time, current_event, history_event, current_seq  # 5 outputs

        elif self.database['sequences'][current_seq_numpy]['seq_feature'] is not None \
                and self.database['event_features'] is None:
            seq_feature = self.database['sequences'][current_seq_numpy]['seq_feature']
            seq_feature = torch.from_numpy(seq_feature)
            seq_feature = seq_feature.type(torch.FloatTensor)

            return current_time, history_time, current_event, history_event, current_seq, seq_feature  # 6 outputs

        elif self.database['sequences'][current_seq_numpy]['seq_feature'] is None \
                and self.database['event_features'] is not None:
            current_event_feature = self.database['event_features'][:, current_event_numpy]
            current_event_feature = torch.from_numpy(current_event_feature)
            current_event_feature = current_event_feature.type(torch.FloatTensor)

            history_event_feature = self.database['event_features'][:, history_event_numpy]
            history_event_feature = torch.from_numpy(history_event_feature)
            history_event_feature = history_event_feature.type(torch.FloatTensor)

            return current_time, history_time, current_event, history_event, current_seq, \
                current_event_feature, history_event_feature  # 7 outputs
        else:
            seq_feature = self.database['sequences'][current_seq_numpy]['seq_feature']
            seq_feature = torch.from_numpy(seq_feature)
            seq_feature = seq_feature.type(torch.FloatTensor)

            current_event_feature = self.database['event_features'][:, current_event_numpy]
            current_event_feature = torch.from_numpy(current_event_feature)
            current_event_feature = current_event_feature.type(torch.FloatTensor)

            history_event_feature = self.database['event_features'][:, history_event_numpy]
            history_event_feature = torch.from_numpy(history_event_feature)
            history_event_feature = history_event_feature.type(torch.FloatTensor)

            return current_time, history_time, current_event, history_event, current_seq, \
                seq_feature, current_event_feature, history_event_feature  # 8 outputs


class SequenceSampler(Dataset):
    """
    Load event sequences with labels via minbatch
    """
    def __init__(self, database, memorysize: int=None):
        """
        :param database: the observed event sequences
            database = {'event_features': None or (C, De) float array of event's static features,
                                      C is the number of event types.
                        'type2idx': a Dict = {'event_name': event_index}
                        'idx2type': a Dict = {event_index: 'event_name'}
                        'seq2idx': a Dict = {'seq_name': seq_index}
                        'idx2seq': a Dict = {seq_index: 'seq_name'}
                        'sequences': a List  = {seq_1, seq_2, ..., seq_N}.
                        }

            For the i-th sequence:
            seq_i = {'times': (N,) float array of timestamps, N is the number of events.
                     'events': (N,) int array of event types.
                     'seq_feature': None or (Ds,) float array of sequence's static feature.
                     't_start': a float number indicating the start timestamp of the sequence.
                     't_stop': a float number indicating the stop timestamp of the sequence.
                     'label': None or int number indicating the labels of the sequence}
        :param memorysize: how many historical events remembered by each event
            When memorysize = None
                All events in a sequence will be considered.
                In that case, each batch can only contain one sequence because different sequences may have different
                length.
            When memorysize = K
                We only memory the last K events of each sequence.
                For the sequence with <K events, we fill virtual event "0" to the beginning of the sequence.
        """
        self.event_cell = []
        self.time_cell = []
        self.database = database
        self.memory_size = memorysize
        if self.memory_size is None:
            logger.warning("Because memory size is not given, the sampler can only sample 1 sequence per batch.")
            logger.warning("Please set batch size = 1 in your code.")

        for i in range(len(database['sequences'])):
            seq_i = database['sequences'][i]
            times = seq_i['times']
            events = seq_i['events']
            t_start = seq_i['t_start']
            target = seq_i['label']
            target_t = seq_i['t_stop']
            if self.memory_size is None:
                former = events
                former_t = times
            else:
                # former = np.zeros((memorysize,), dtype=np.int)
                # former = np.random.permutation(len(self.database['type2idx']))
                # former = former[:memorysize]
                former = np.random.choice(len(self.database['type2idx']), memorysize)
                former_t = t_start * np.ones((memorysize,))

                if 0 < times.shape[0] < memorysize:
                    former[-memorysize:] = events
                    former_t[-memorysize:] = times
                else:
                    former = events[-memorysize:]
                    former_t = times[-memorysize:]

            self.event_cell.append((target, former, i))
            self.time_cell.append((target_t, former_t))
        logger.info('In this dataset, the number of sequences = {}.'.format(len(self.event_cell)))

    def __len__(self):
        return len(self.event_cell)

    def __getitem__(self, idx):
        current_time = torch.Tensor([self.time_cell[idx][0]])  # torch.from_numpy()
        current_time = current_time.type(torch.FloatTensor)
        history_time = torch.from_numpy(self.time_cell[idx][1])
        history_time = history_time.type(torch.FloatTensor)

        current_event_numpy = self.event_cell[idx][0]
        current_event = torch.Tensor([self.event_cell[idx][0]])
        current_event = current_event.type(torch.LongTensor)
        history_event_numpy = self.event_cell[idx][1]
        history_event = torch.from_numpy(self.event_cell[idx][1])
        history_event = history_event.type(torch.LongTensor)

        current_seq_numpy = self.event_cell[idx][2]
        current_seq = torch.Tensor([self.event_cell[idx][2]])
        current_seq = current_seq.type(torch.LongTensor)

        if self.database['sequences'][current_seq_numpy]['seq_feature'] is None \
                and self.database['event_features'] is None:
            return current_time, history_time, current_event, history_event, current_seq  # 5 outputs

        elif self.database['sequences'][current_seq_numpy]['seq_feature'] is not None \
                and self.database['event_features'] is None:
            seq_feature = self.database['sequences'][current_seq_numpy]['seq_feature']
            seq_feature = torch.from_numpy(seq_feature)
            seq_feature = seq_feature.type(torch.FloatTensor)

            return current_time, history_time, current_event, history_event, current_seq, seq_feature  # 6 outputs

        elif self.database['sequences'][current_seq_numpy]['seq_feature'] is None \
                and self.database['event_features'] is not None:
            current_event_feature = self.database['event_features'][:, current_event_numpy]
            current_event_feature = torch.from_numpy(current_event_feature)
            current_event_feature = current_event_feature.type(torch.FloatTensor)

            history_event_feature = self.database['event_features'][:, history_event_numpy]
            history_event_feature = torch.from_numpy(history_event_feature)
            history_event_feature = history_event_feature.type(torch.FloatTensor)

            return current_time, history_time, current_event, history_event, current_seq, \
                current_event_feature, history_event_feature  # 7 outputs
        else:
            seq_feature = self.database['sequences'][current_seq_numpy]['seq_feature']
            seq_feature = torch.from_numpy(seq_feature)
            seq_feature = seq_feature.type(torch.FloatTensor)

            current_event_feature = self.database['event_features'][:, current_event_numpy]
            current_event_feature = torch.from_numpy(current_event_feature)
            current_event_feature = current_event_feature.type(torch.FloatTensor)

            history_event_feature = self.database['event_features'][:, history_event_numpy]
            history_event_feature = torch.from_numpy(history_event_feature)
            history_event_feature = history_event_feature.type(torch.FloatTensor)

            return current_time, history_time, current_event, history_event, current_seq, \
                seq_feature, current_event_feature, history_event_feature  # 8 outputs


def samples2dict(samples, device, Cs, FCs):
    """
    Convert a batch sampled from dataloader to a dictionary
    :param samples: a batch of data sampled from the "dataloader" defined by EventSampler
    :param device: a string representing usable CPU or GPU
    :param Cs: 'Cs': (num_type, 1) LongTensor containing all events' index
    :param FCs: 'FCs': None or a (num_type, Dc) FloatTensor representing all events' features
    :return:
        ci: events (batch_size, 1) LongTensor indicates each event's type in the batch
        batch_dict = {
            'ci': events (batch_size, 1) LongTensor indicates each event's type in the batch
            'cjs': history (batch_size, memory_size) LongTensor indicates historical events' types in the batch
            'ti': event_time (batch_size, 1) FloatTensor indicates each event's timestamp in the batch
            'tjs': history_time (batch_size, memory_size) FloatTensor represents history's timestamps in the batch
            'sn': sequence index (batch_size, 1) LongTensor
            'fsn': features (batch_size, dim_feature) FloatTensor contains feature vectors of the sequence in the batch
            'fci': current_feature (batch_size, Dc) FloatTensor of current feature
            'fcjs': history_features (batch_size, Dc, memory_size) FloatTensor of historical features
            'Cs': the input Cs
            'FCs': the input FCs
            }
    """
    ti = samples[0].to(device)
    tjs = samples[1].to(device)
    ci = samples[2].to(device)
    cjs = samples[3].to(device)
    sn = samples[4].to(device)
    if len(samples) == 5:
        fsn = None
        fci = None
        fcjs = None
    elif len(samples) == 6:
        fsn = samples[5].to(device)
        fci = None
        fcjs = None
    elif len(samples) == 7:
        fsn = None
        fci = samples[5].to(device)
        fcjs = samples[6].to(device)
    else:
        fsn = samples[5].to(device)
        fci = samples[6].to(device)
        fcjs = samples[7].to(device)

    batch_dict = {'ti': ti,
                  'tjs': tjs,
                  'ci': ci,
                  'cjs': cjs,
                  'sn': sn,
                  'fsn': fsn,
                  'fci': fci,
                  'fcjs': fcjs,
                  'Cs': Cs,
                  'FCs': FCs}
    return ci, batch_dict


def enumerate_all_events(database, seq_id, use_cuda):
    """
    Build a dictionary containing all events' basic information (i.e., index and features) for a specific event sequence
    :param database: the proposed database with the format defined above
    :param seq_id: the index of the target sequence
    :param use_cuda: whether move data to GPU (true) or not (false)
    :return:
        event_dict: a dictionary containing all events' basic information
        event_dict = {
            'ci': (num_type, 1) LongTensor containing all events' index
            'sn': (num_type, 1) LongTensor repeating the proposed sequence id "num_type" times
            'fsn': None or a (num_type, dim_feature) FloatTensor repeating the sequence' feature "num_type" times
            'Cs': (num_type, 1) LongTensor containing all events' index
            'FCs': None or a (num_type, dim_feature) FloatTensor representing all events' features
            }
    """
    device = torch.device('cuda:0' if use_cuda else 'cpu')

    Cs = torch.LongTensor(list(range(len(database['type2idx']))))
    Cs = Cs.view(-1, 1)
    Cs = Cs.to(device)

    if database['event_features'] is not None:
        all_event_feature = torch.from_numpy(database['event_features'])
        FCs = all_event_feature.type(torch.FloatTensor)
        FCs = torch.t(FCs)    # (num_type, dim_features)
        FCs = FCs.to(device)
    else:
        FCs = None

    sn = torch.LongTensor([seq_id])
    sn = sn.view(1, 1).repeat(len(database['type2idx']), 1)
    sn = sn.to(device)
    if database['sequences'][seq_id]['seq_feature'] is not None:
        fsn = torch.from_numpy(database['sequences'][seq_id]['seq_feature'])
        fsn = fsn.type(torch.FloatTensor)
        fsn = fsn.view(1, -1).repeat(len(database['type2idx']), 1)
        fsn = fsn.to(device)
    else:
        fsn = None

    event_dict = {'ci': Cs,
                  'sn': sn,
                  'fsn': fsn,
                  'Cs': Cs,
                  'FCs': FCs}
    return event_dict


def data_info(database):
    """
    Print basic information of proposed database
    :param database: the database with the format mentioned above
    """
    logger.info('** Statistics of Target Database **')
    logger.info('- The number of event types = {}.'.format(len(database['type2idx'])))
    logger.info('- The number of sequences = {}.'.format(len(database['seq2idx'])))
    if database['event_features'] is not None:
        logger.info('- Each event has a feature vector with dimension {}.'.format(
            database['event_features'].shape[1]))
    else:
        logger.info('- Event feature is None.')

    if database['sequences'][0]['seq_feature'] is not None:
        logger.info('- Each sequence has a feature vector with dimension {}.'.format(
            database['sequences'][0]['seq_feature'].shape[0]))
    else:
        logger.info('- Sequence feature is None.')

    N_max = 0
    N_min = np.inf
    N_mean = 0
    for i in range(len(database['sequences'])):
        num_event = database['sequences'][i]['events'].shape[0]
        N_mean += num_event
        if num_event < N_min:
            N_min = num_event
        if num_event > N_max:
            N_max = num_event
    N_mean /= len(database['sequences'])
    logger.info('- The longest sequence is with {} events.'.format(N_max))
    logger.info('- The shortest sequence is with {} events.'.format(N_min))
    logger.info('- The average number of events per sequence is {:.2f}.'.format(N_mean))
