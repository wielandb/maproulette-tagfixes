import requests
import gzip
import io
import re
import os

STATE_URL = 'https://planet.openstreetmap.org/replication/minute/state.txt'
BASE_URL = 'https://planet.openstreetmap.org/replication/minute'


def get_latest_created_ids():
    """
    Fetch the most recent minute replication state, download successive .osc.gz change files,
    and return the latest created IDs for node, way, and relation.

    Returns:
        dict: {'node': int, 'way': int, 'relation': int}
    """
    # If there is a latest_created_ids.json file and it was last modified within the last 24 hours,
    # return the contents of that file instead of fetching new data.
    try:
        if os.path.exists('latest_created_ids.json'):
            last_modified = os.path.getmtime('latest_created_ids.json')
            if (time.time() - last_modified) < 24 * 60 * 60:
                with open('latest_created_ids.json', 'r') as f:
                    return eval(f.read())
    except Exception as e:
        print(f"Error checking latest_created_ids.json: {e}")
    # Download state.txt
    resp = requests.get(STATE_URL)
    resp.raise_for_status()

    # Parse sequenceNumber
    seq = None
    for line in resp.text.splitlines():
        if line.startswith('sequenceNumber='):
            seq = int(line.split('=', 1)[1])
            break
    if seq is None:
        raise RuntimeError('Could not parse sequenceNumber from state.txt')

    # Prepare storage for max created IDs
    max_ids = {'node': None, 'way': None, 'relation': None}

    # Walk backwards through replication files until all three types are found
    for s in range(seq, 0, -1):
        # Build URL in /aaa/bbb/ccc.osc.gz format
        seq_str = str(s).zfill(9)
        parts = [seq_str[i:i+3] for i in range(0, 9, 3)]
        url = f"{BASE_URL}/{parts[0]}/{parts[1]}/{parts[2]}.osc.gz"

        resp = requests.get(url)
        if resp.status_code != 200:
            # Missing file, skip
            continue

        # Decompress and scan for <create> blocks
        with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as f:
            in_create = False
            for raw_line in f:
                line = raw_line.decode('utf-8', errors='ignore')
                if '<create' in line:
                    in_create = True
                    continue
                if '</create' in line:
                    in_create = False
                    continue

                if in_create:
                    m = re.match(r"\s*<(node|way|relation)\b[^>]*\bid=\"(\d+)\"", line)
                    if m:
                        typ, id_str = m.groups()
                        id_val = int(id_str)
                        if max_ids[typ] is None or id_val > max_ids[typ]:
                            max_ids[typ] = id_val

        # Stop early if all found
        if all(v is not None for v in max_ids.values()):
            break

    # Write max IDs to file and return them
    with open('latest_created_ids.json', 'w') as f:
        f.write(f"{max_ids}\n")
    return max_ids


def get_id_percentile(object_type, obj_id):
    """
    Compute the percentile of a given OSM object ID relative to the latest created max ID.

    Args:
        object_type (str): One of 'node', 'way', 'relation'.
        obj_id (int): The object ID to evaluate.

    Returns:
        float: Percentile (0-100). Raises ValueError if inputs are invalid.
    """
    if object_type not in ('node', 'way', 'relation'):
        raise ValueError(f"Invalid object_type: {object_type}")

    max_ids = get_latest_created_ids()
    max_id = max_ids[object_type]
    if max_id is None:
        raise RuntimeError(f"Max ID for {object_type} could not be determined.")

    if obj_id > max_id:
        raise ValueError(f"{object_type} ID {obj_id} is greater than current max {max_id}.")

    return (obj_id / max_id) * 100


if __name__ == '__main__':
    latest = get_latest_created_ids()
    print('Latest created IDs:', latest)
