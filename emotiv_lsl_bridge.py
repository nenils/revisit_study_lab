import json
import os
import ssl
import websocket
from pylsl import StreamInfo, StreamOutlet

CORTEX_URL = "wss://localhost:6868"
CLIENT_ID = os.environ.get("EMOTIV_CLIENT_ID")
CLIENT_SECRET = os.environ.get("EMOTIV_CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError("Set EMOTIV_CLIENT_ID and EMOTIV_CLIENT_SECRET first.")

BANDS = ["theta", "alpha", "low_beta", "high_beta", "gamma"]
SENSORS = [
    "AF3", "F7", "F3", "FC5", "T7", "P7",
    "O1", "O2", "P8", "T8", "FC6", "F4",
    "F8", "AF4"]
POW_CHANNELS = [f"{sensor}_{band}" for sensor in SENSORS for band in BANDS]


def rpc(ws, method, params=None, request_id=1):
    msg = {
        "jsonrpc": "2.0",
        "method": method,
        "id": request_id
    }
    if params is not None:
        msg["params"] = params

    ws.send(json.dumps(msg))

    while True:
        response = json.loads(ws.recv())
        if response.get("id") == request_id:
            if "error" in response:
                raise RuntimeError(f"{method} failed: {response['error']}")
            return response.get("result")


print("Connecting to Cortex...")
ws = websocket.create_connection(
    CORTEX_URL,
    sslopt={"cert_reqs": ssl.CERT_NONE}
)

print("Connected.")

print("Requesting access. Check Emotiv Launcher and approve the app...")
access = rpc(ws, "requestAccess", {
    "clientId": CLIENT_ID,
    "clientSecret": CLIENT_SECRET
}, 100)
print(access)

input("After approving in Emotiv Launcher, press Enter here...")

print("Authorizing...")
auth = rpc(ws, "authorize", {
    "clientId": CLIENT_ID,
    "clientSecret": CLIENT_SECRET,
    "debit": 10
}, 2)

token = auth["cortexToken"]
print("Authorized.")

print("Querying headsets...")
headsets = rpc(ws, "queryHeadsets", {}, 3)

if not headsets:
    raise RuntimeError("No Emotiv headset found. Check Emotiv Launcher.")

headset_id = headsets[0]["id"]
print(f"Using headset: {headset_id}")

print("Creating session...")
session = rpc(ws, "createSession", {
    "cortexToken": token,
    "headset": headset_id,
    "status": "active"
}, 4)

session_id = session["id"]
print(f"Session created: {session_id}")

print("Creating LSL outlet...")
info = StreamInfo(
    name="Emotiv Band Power",
    type="BandPower",
    channel_count=len(POW_CHANNELS),
    nominal_srate=8,
    channel_format="float32",
    source_id=f"emotiv-pow-{headset_id}"
)

desc = info.desc()
desc.append_child_value("manufacturer", "Emotiv")
channels = desc.append_child("channels")

for label in POW_CHANNELS:
    ch = channels.append_child("channel")
    ch.append_child_value("label", label)
    ch.append_child_value("unit", "power")
    ch.append_child_value("type", "BandPower")

outlet = StreamOutlet(info)

print("Subscribing to band power...")
sub = rpc(ws, "subscribe", {
    "cortexToken": token,
    "session": session_id,
    "streams": ["pow"]
}, 5)

print("Subscribed:")
print(sub)
print("Publishing LSL stream: Emotiv Band Power")
print("Press Ctrl+C to stop.")

try:
    while True:
        packet = json.loads(ws.recv())

        if "pow" not in packet:
            continue

        pow_values = packet["pow"]

        # Cortex usually sends: [timestamp, AF3/theta, AF3/alpha, ..., AF4/gamma]
        values = pow_values

        if len(values) != len(POW_CHANNELS):
            print(f"Unexpected POW length: {len(values)} | {values}")
            continue

        sample = [float(x) for x in values]
        outlet.push_sample(sample)

except KeyboardInterrupt:
    print("Stopping...")

finally:
    try:
        rpc(ws, "unsubscribe", {
            "cortexToken": token,
            "session": session_id,
            "streams": ["pow"]
        }, 6)
    except Exception:
        pass

    try:
        rpc(ws, "updateSession", {
            "cortexToken": token,
            "session": session_id,
            "status": "close"
        }, 7)
    except Exception:
        pass

    ws.close()
    print("Stopped.")