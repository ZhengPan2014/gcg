import os
import argparse
import yaml

from gcg.algos.gcg import run_gcg

parser = argparse.ArgumentParser()
parser.add_argument('--exps', nargs='+')
args = parser.parse_args()

for exp in args.exps:
    yaml_path = os.path.abspath('../yamls/{0}.yaml'.format(exp))
    assert(os.path.exists(yaml_path))
    with open(yaml_path, 'r') as f:
        params = yaml.load(f)
    with open(yaml_path, 'r') as f:
        params_txt = ''.join(f.readlines())
    params['txt'] = params_txt

    run_gcg(params)