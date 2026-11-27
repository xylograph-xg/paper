"""Offline JSON in/out; never reads catalog, source PDFs, gold or production sidecar."""
import argparse
import json
import sys
from .api import classify_level2
from .claim_api import classify_claims


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--strategy',choices=('retrieval','assertion_graph','claim_frames'),required=True)
    args=p.parse_args();documents=json.load(sys.stdin)
    if not isinstance(documents,list):raise ValueError('须输入冻结文献数组')
    predictions=[classify_claims(d) if args.strategy=='claim_frames' else classify_level2(d,args.strategy) for d in documents]
    json.dump(predictions,sys.stdout,ensure_ascii=False,indent=2)


if __name__=='__main__':main()
