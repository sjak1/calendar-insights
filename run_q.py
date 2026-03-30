import json
from opensearch_client import run_raw_dsl  # this is already in your repo

def main():
    dsl = {
        "query": {
            "bool": {
                "filter": [
                    {
                        "terms": {
                            "eventName.keyword": [
                                "Alphabet",
                                "Honda",
                                "Spirit AeroSystems",
                            ]
                        }
                    },
                    {
                        "term": {
                            "location.data.locationName.keyword": "Redwood Shores"
                        }
                    },
                ]
            }
        },
        "size": 20,
        "_source": [
            "eventName",
            "eventId",
            "startTime",
            "duration",
            "timezone",
            "status.stateName",
            "location.data.locationName",
            "eventData.VISIT_INFO.data.customerName",
        ],
        "sort": [
            {
                "startTime": {
                    "order": "asc",
                }
            }
        ],
    }

    # size_cap=None disables the 50 cap in run_raw_dsl
    result = run_raw_dsl(dsl_body=dsl, index=None, query_timezone="America/Los_Angeles", size_cap=None)

    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    main()