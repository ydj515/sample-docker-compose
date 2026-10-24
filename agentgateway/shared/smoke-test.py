"""Verify MCP initialization, tool discovery, and echo through agentgateway."""

import json
import sys
import urllib.request


def main():
    endpoint = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3000/mcp"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    def rpc(method, params, request_id=None):
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            payload["id"] = request_id

        request = urllib.request.Request(
            endpoint, data=json.dumps(payload).encode(), headers=headers
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            session = response.headers.get("Mcp-Session-Id")
            if session:
                headers["Mcp-Session-Id"] = session

            if request_id is None:
                return None

            if "text/event-stream" in response.headers.get("Content-Type", ""):
                result = None
                for line in response:
                    if line.startswith(b"data:"):
                        candidate = json.loads(line[5:])
                        if candidate.get("id") == request_id:
                            result = candidate
                            break

                if result is None:
                    raise RuntimeError("No JSON-RPC response in SSE stream")
            else:
                result = json.load(response)

            if result.get("id") != request_id or "error" in result:
                raise RuntimeError(f"JSON-RPC request failed: {method}")

            return result["result"]

    initialized = rpc("initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "agentgateway-smoke-test", "version": "1.0.0"},
    }, 1)
    headers["MCP-Protocol-Version"] = initialized["protocolVersion"]
    rpc("notifications/initialized", {})
    tools = rpc("tools/list", {}, 2)["tools"]
    echo = next((tool["name"] for tool in tools
                 if tool["name"] == "echo" or tool["name"].endswith(":echo")), None)
    if echo is None:
        raise RuntimeError("Echo tool was not discovered")

    message = "hello through agentgateway"
    result = rpc("tools/call", {"name": echo, "arguments": {"message": message}}, 3)
    if result.get("isError") or not any(
        message in item.get("text", "") for item in result["content"]
    ):
        raise RuntimeError("Echo tool did not return the expected message")

    add = next((tool["name"] for tool in tools
                if tool["name"] == "add" or tool["name"].endswith(":add")), None)
    if add is None:
        raise RuntimeError("Add tool was not discovered")

    total = rpc("tools/call", {"name": add, "arguments": {"a": -3, "b": 1.5}}, 4)
    if total.get("isError") or total["content"][0].get("text") != "-1.5":
        raise RuntimeError("Add tool returned an incorrect sum")

    try:
        invalid = rpc("tools/call", {"name": add, "arguments": {"a": "bad", "b": 1}}, 5)
    except RuntimeError as exc:
        if str(exc) != "JSON-RPC request failed: tools/call":
            raise
    else:
        if not invalid.get("isError"):
            raise RuntimeError("Invalid arguments were accepted")

    print("PASS: add result and invalid argument rejection")
    print(f"PASS: initialize, tools/list ({len(tools)} tools), tools/call ({echo})")


if __name__ == "__main__":
    main()
