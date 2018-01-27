import os
import argparse
import yaml

from gcg.algos.async_gcg import run_async_gcg_train, run_async_gcg_inference

parser = argparse.ArgumentParser()
parser.add_argument('exp', type=str)
parser.add_argument('async', type=str, choices=('train', 'inference'))
args = parser.parse_args()

yaml_path = os.path.abspath('../yamls/{0}.yaml'.format(args.exp))
assert(os.path.exists(yaml_path))
with open(yaml_path, 'r') as f:
    params = yaml.load(f)
with open(yaml_path, 'r') as f:
    params_txt = ''.join(f.readlines())
params['txt'] = params_txt

if args.async == 'train':
    run_async_gcg_train(params)
elif args.async == 'inference':
    run_async_gcg_inference(params)
else:
    raise NotImplementedError