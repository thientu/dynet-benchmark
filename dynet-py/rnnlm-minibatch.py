from collections import Counter, defaultdict
from itertools import count
import math
import random
import time
import sys

import dynet as dy
import numpy as np

# format of files: each line is "word1/tag2 word2/tag2 ..."
train_file="data/text/train.txt"
test_file="data/text/dev.txt"

MB_SIZE = 10

class Vocab:
    def __init__(self, w2i=None):
        if w2i is None: w2i = defaultdict(count(0).next)
        self.w2i = dict(w2i)
        self.i2w = {i:w for w,i in w2i.iteritems()}
    @classmethod
    def from_corpus(cls, corpus):
        w2i = defaultdict(count(0).next)
        for sent in corpus:
            [w2i[word] for word in sent]
        return Vocab(w2i)

    def size(self): return len(self.w2i.keys())

def read(fname):
    """
    Read a file where each line is of the form "word1 word2 ..."
    Yields lists of the form [word1, word2, ...]
    """
    with file(fname) as fh:
        for line in fh:
            sent = line.strip().split()
            sent.append("<s>")
            yield sent

train=list(read(train_file))
test=list(read(test_file))
words=[]
wc=Counter()
for sent in train:
    for w in sent:
        words.append(w)
        wc[w]+=1

vw = Vocab.from_corpus([words])
S = vw.w2i["<s>"]

nwords = vw.size()

# DyNet Starts

model = dy.Model()
trainer = dy.AdamTrainer(model)

# Lookup parameters for word embeddings
WORDS_LOOKUP = model.add_lookup_parameters((nwords, 64))

# Word-level LSTM (layers=1, input=64, output=128, model)
RNN = dy.LSTMBuilder(1, 64, 128, model)

# Softmax weights/biases on top of LSTM outputs
W_sm = model.add_parameters((nwords, 128))
b_sm = model.add_parameters(nwords)

# Build the language model graph
def calc_lm_loss(sents):

    dy.renew_cg()
    # parameters -> expressions
    W_exp = dy.parameter(W_sm)
    b_exp = dy.parameter(b_sm)

    # initialize the RNN
    f_init = RNN.initial_state()

    # get the wids and masks for each step
    tot_words = 0
    wids = []
    masks = []
    for i in range(len(sents[0])):
        wids.append([
          (vw.w2i[sent[i]] if len(sent)>i else S) for sent in sents])
        mask = [(1 if len(sent)>i else 0) for sent in sents]
        masks.append(mask)
        tot_words += sum(mask)
    
    # start the rnn by inputting "<s>"
    init_ids = [S] * len(sents)
    s = f_init.add_input(dy.lookup_batch(WORDS_LOOKUP,init_ids))

    # feed word vectors into the RNN and predict the next word    
    losses = []
    for wid, mask in zip(wids, masks):
        # calculate the softmax and loss      
        score = W_exp * s.output() + b_exp
        loss = dy.pickneglogsoftmax_batch(score, wid)
        # mask the loss if at least one sentence is shorter
        if mask[-1] != 1:
            mask_expr = dy.inputVector(mask)
            mask_expr = dy.reshape(mask_expr, (1,), MB_SIZE)
            loss = loss * mask_expr
        losses.append(loss)
        # update the state of the RNN        
        wemb = dy.lookup_batch(WORDS_LOOKUP, wid)
        s = s.add_input(wemb) 
    
    return dy.sum_batches(dy.esum(losses)), tot_words

start = time.time()
i = all_time = all_tagged = this_words = this_loss = 0
# Sort training sentences in descending order and count minibatches
train.sort(key=lambda x: -len(x))
test.sort(key=lambda x: -len(x))
train_order = [x*MB_SIZE for x in range((len(train)-1)/MB_SIZE + 1)]
test_order = [x*MB_SIZE for x in range((len(test)-1)/MB_SIZE + 1)]
# Perform training
for ITER in xrange(50):
    random.shuffle(train_order)
    for sid in train_order: 
        i += 1
        if i % (500/MB_SIZE) == 0:
            trainer.status()
            print this_loss / this_words
            all_tagged += this_words
            this_words = this_loss = 0
        if i % (10000/MB_SIZE) == 0:
            all_time += time.time() - start
            dev_loss = dev_words = 0
            for sid in test_order:
                loss_exp, mb_words = calc_lm_loss(test[sid:sid+MB_SIZE])
                dev_loss += loss_exp.scalar_value()
                dev_words += mb_words
            print ("nll=%.4f, ppl=%.4f, time=%.4f, word_per_sec=%.4f" % (dev_loss/dev_words, math.exp(dev_loss/dev_words), all_time, all_tagged/all_time))
            if all_time > 300:
                sys.exit(0)
        # train on the minibatch
        loss_exp, mb_words = calc_lm_loss(train[sid:sid+MB_SIZE])
        this_loss += loss_exp.scalar_value()
        this_words += mb_words
        loss_exp.backward()
        trainer.update()
    print "epoch %r finished" % ITER
    trainer.update_epoch(1.0)


