#!/usr/bin/env bash

set -e

ENV=pytorch-yolo-v3
conda create -n $ENV pytorch==0.4 cuda90 -c pytorch -y
source activate $ENV
conda install pandas pillow matplotlib -y
conda install opencv -y