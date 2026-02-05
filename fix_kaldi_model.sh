#!/bin/bash
# Inside Container
echo "Searching for words.txt in /opt/kaldi..."
find /opt/kaldi -name "words.txt"
echo "Searching for L.fst in /opt/kaldi..."
find /opt/kaldi -name "L.fst"
