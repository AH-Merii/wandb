#!/bin/bash
set -e
rm -rf nexus-py-1
virtualenv nexus-py-1
source nexus-py-1/bin/activate
pip install --upgrade pip
cd ../lib
./build_proto.sh
./build_lib.sh
pip install .
echo "Run:"
echo "source nexus-py-1/bin/activate"
