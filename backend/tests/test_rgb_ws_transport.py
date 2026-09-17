import asyncio
import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from rgb_ws_transport import cursor, packet, serve_latest

def test_packet_preserves_jpeg_and_cursor_validation():
    data=b'\xff\xd8jpeg\xff\xd9'
    p=packet(SimpleNamespace(status_code=200,headers={'x-test':'value'},body=data))
    n=struct.unpack('!I',p[:4])[0]
    assert p[4+n:]==data
    assert json.loads(p[4:4+n])['status']==200
    assert cursor('{"session":"","after":0}')==('',0)
    for text in ['{}','[]','{"session":"","after":true}','{"session":"x","after":0}','{"session":"","after":-1}','x'*513]:
        with pytest.raises(ValueError):cursor(text)

def test_latest_selected_on_each_request_and_bad_request_closes():
    async def run():
        calls=[]
        class Socket:
            def __init__(self):self.requests=iter(['{"session":"","after":0}','{"session":"'+ 'a'*32 +'","after":1}','{}']);self.sent=[];self.closed=None
            async def receive_text(self):return next(self.requests)
            async def send_bytes(self,p):self.sent.append(p)
            async def close(self,code):self.closed=code
        ws=Socket()
        async def response(s,n):
            calls.append((s,n))
            return SimpleNamespace(status_code=200,headers={},body=b'jpeg')
        await serve_latest(ws,response)
        assert calls==[('',0),('a'*32,1)] and len(ws.sent)==2 and ws.closed==1008
    asyncio.run(run())
