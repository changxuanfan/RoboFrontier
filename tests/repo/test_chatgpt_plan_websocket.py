import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chatgpt_websocket_fixture import ProviderSocket
import claude_chatgpt_gateway as gateway


class APIAdmissionTests(unittest.TestCase):
    def test_token_reservations_remain_charged_until_the_window_expires(self):
        admission=gateway.Admission(1,reservation=1,concurrency=2,window=.2)
        with admission.reserve(threading.Event(),{}):pass
        entered=threading.Event()
        def wait():
            record={}
            with admission.reserve(threading.Event(),record):entered.set()
            return record
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(wait)
            self.assertFalse(entered.wait(.04))
            self.assertGreaterEqual(future.result(timeout=2)['api_admission_wait_s'],.1)
        self.assertEqual(admission.active,0)

    def test_cancelled_fifo_waiter_cannot_block_the_next_session_or_leak_an_inflight_slot(self):
        admission=gateway.Admission(3,reservation=1,concurrency=1,window=1)
        cancel=threading.Event();entered=threading.Event()
        def wait(event):
            with admission.reserve(event,{}):entered.set()
        with ThreadPoolExecutor(max_workers=2) as pool:
            with admission.reserve(threading.Event(),{}):
                cancelled=pool.submit(wait,cancel)
                deadline=time.monotonic()+1
                while not admission.queue and time.monotonic()<deadline:time.sleep(.005)
                cancel.set()
                with self.assertRaises(ConnectionResetError):cancelled.result(timeout=2)
                following=pool.submit(wait,threading.Event())
                self.assertFalse(entered.wait(.02))
            following.result(timeout=2)
        self.assertEqual(admission.active,0);self.assertFalse(admission.queue)


class WebSocketStateTests(unittest.TestCase):
    def setUp(self):
        self.sockets=[];self.calls=[];self.token='fixture'
        def reply(request):
            self.calls.append(request)
            return {'id':'resp_'+str(len(self.calls)),'model':gateway.MODEL,'status':'completed',
                    'output':[{'id':'msg_'+str(len(self.calls)),'type':'message','role':'assistant',
                    'phase':'final_answer','content':[{'type':'output_text','text':'OK'}]}]}
        self.reply=reply
        def connect(token):
            socket=ProviderSocket(self.reply);self.sockets.append(socket);return socket
        self.transport=gateway.WebSocketTransport(SimpleNamespace(access_token=lambda:self.token),connect,timeout=.1)
        self.addCleanup(self.transport.close)

    def request(self,session='parent',items=None,**settings):
        history=gateway.InputHistory(session)
        history.extend(items if items is not None else [{'role':'user','content':'fixture'}])
        return {'model':gateway.MODEL,'input':history,'stream':True,'store':False,**settings}

    def turn(self,request,cancelled=None):
        record={}
        with self.transport.exchange(request,cancelled or threading.Event(),record) as result:
            return result,record

    def continued(self,request,result,new=None):
        return self.request(request['input'].session_id,list(request['input'])+result['output']+
                            (new or [{'role':'user','content':'next'}]),
                            **{k:v for k,v in request.items() if k not in ('model','input','stream','store')})

    def test_only_new_tool_image_is_sent_and_original_reasoning_is_retained(self):
        def reply(request):
            self.calls.append(request)
            return {'id':'resp_'+str(len(self.calls)),'model':gateway.MODEL,'status':'completed','output':[
                {'type':'reasoning','id':'rs_1','summary':[],'encrypted_content':'original'},
                {'type':'function_call','call_id':'call_1','name':'robot','namespace':'robot_frontier',
                 'arguments':'{ "op": "observe" }','status':'completed'}]}
        self.reply=reply
        first=self.request();result,_=self.turn(first)
        image={'type':'function_call_output','call_id':'call_1','output':[
            {'type':'input_image','image_url':'data:image/png;base64,aW1hZ2U='}]}
        second=self.continued(first,result,[image]);_,record=self.turn(second)
        self.assertEqual(self.sockets[0].wire[1]['input'],[image])
        self.assertEqual(self.sockets[0].wire[1]['previous_response_id'],result['id'])
        self.assertEqual(self.calls[1]['input'],list(second['input']))
        self.assertEqual(record['ws_mode'],'incremental')

    def test_completed_retry_reuses_response_without_another_model_call(self):
        request=self.request();first,_=self.turn(request);second,record=self.turn(request)
        self.assertEqual(first,second);self.assertEqual(len(self.calls),1)
        self.assertFalse(record['upstream_sent']);self.assertEqual(record['ws_mode'],'completed_retry')

    def test_restart_replays_full_verified_history_without_old_response_reference(self):
        request=self.request();result,_=self.turn(request);next_request=self.continued(request,result)
        self.transport.close()
        self.transport=gateway.WebSocketTransport(SimpleNamespace(access_token=lambda:self.token),
            lambda token:ProviderSocket(self.reply))
        _,record=self.turn(next_request)
        self.assertEqual(record['ws_mode'],'full_replay')
        self.assertIsNone(record['previous_response_id'])
        self.assertEqual(self.calls[-1]['input'],list(next_request['input']))

    def test_compaction_and_setting_change_start_new_context(self):
        for field in ('history','settings'):
            with self.subTest(field=field):
                request=self.request(session=field,instructions='old');result,_=self.turn(request)
                changed=self.request(session=field,items=[{'role':'user','content':'summary'}],instructions='old') if field=='history' else self.continued(request,result)
                if field=='settings':changed['instructions']='new'
                _,record=self.turn(changed)
                self.assertEqual(record['ws_mode'],'full_replay')
                self.assertEqual(record['ws_reset_reason'],'history_replaced' if field=='history' else 'settings_changed')

    def test_token_rotation_rebuilds_connection_with_full_history(self):
        request=self.request();result,_=self.turn(request);self.token='renewed'
        _,record=self.turn(self.continued(request,result))
        self.assertEqual(record['ws_reset_reason'],'credential_refreshed')
        self.assertEqual(len(self.sockets),2)

    def test_connection_lifetime_is_rotated_before_provider_deadline(self):
        request=self.request();result,_=self.turn(request)
        self.transport.channels['parent'].born-=3600
        _,record=self.turn(self.continued(request,result))
        self.assertEqual(record['ws_reset_reason'],'connection_lifetime')

    def test_missing_response_recovery_is_bounded_and_replays_complete_history(self):
        request=self.request();result,_=self.turn(request);self.sockets[0].responses.clear()
        next_request=self.continued(request,result);_,record=self.turn(next_request)
        self.assertEqual(record['ws_recovery'],'previous_response_not_found')
        self.assertEqual(len(self.sockets),2)
        self.assertEqual(self.sockets[1].wire[0]['input'],list(next_request['input']))
        self.assertNotIn('previous_response_id',self.sockets[1].wire[0])

    def test_fork_proceeds_while_parent_turn_is_blocked(self):
        self.transport.admission=gateway.Admission(10,reservation=1,concurrency=2)
        request=self.request();result,_=self.turn(request)
        entered=threading.Event();release=threading.Event();original=self.reply
        def reply(payload):
            if payload['input'][-1].get('content')=='blocked':
                entered.set();self.assertTrue(release.wait(3))
            return original(payload)
        self.reply=reply;self.sockets[0].reply=reply
        parent=self.continued(request,result,[{'role':'user','content':'blocked'}])
        child=self.request('child',list(request['input'])+result['output']+[{'role':'user','content':'child'}])
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending=pool.submit(self.turn,parent)
            try:
                self.assertTrue(entered.wait(1))
                _,record=pool.submit(self.turn,child).result(timeout=1)
                self.assertEqual(record['ws_mode'],'full_replay')
                self.assertIsNone(record['previous_response_id'])
            finally:release.set()
            pending.result(timeout=2)

    def test_failed_persistence_never_commits_connection_state(self):
        with self.assertRaises(OSError):
            with self.transport.exchange(self.request(),threading.Event(),{}) as result:
                raise OSError('fixture storage failure')
        self.assertIsNone(self.transport.channels['parent'].response_id)
        self.assertTrue(self.sockets[0].closed)

    def test_cancel_and_incomplete_response_fail_without_hidden_resubmission(self):
        class BrokenSocket:
            def send(self,payload):self.sent=payload
            def recv(self,timeout):return json.dumps({'type':'response.incomplete','response':{}})
            def close(self):pass
        self.transport.connect=lambda token:BrokenSocket()
        with self.assertRaises(gateway.UpstreamError):self.turn(self.request())
        self.assertIsNone(self.transport.channels['parent'].socket)
        cancel=threading.Event();cancel.set()
        with self.assertRaises(ConnectionResetError):self.turn(self.request(),cancel)

    def test_connection_close_diagnostics_never_log_peer_reason_or_resubmit(self):
        from websockets.exceptions import ConnectionClosedError
        from websockets.frames import Close
        class Socket:
            sent=0
            def send(self,payload):self.sent+=1
            def recv(self,timeout):raise ConnectionClosedError(Close(1011,'private peer text'),None)
            def close(self):pass
        socket=Socket();self.transport.connect=lambda token:socket;record={}
        with self.assertRaises(ConnectionClosedError):
            with self.transport.exchange(self.request(),threading.Event(),record):pass
        self.assertEqual(socket.sent,1)
        self.assertEqual(record['ws_rcvd_close_code'],1011)
        self.assertFalse(record['ws_response_started'])
        self.assertTrue(record['ws_request_sent'])
        self.assertNotIn('private peer text',json.dumps(record))
        self.assertIsNone(self.transport.channels['parent'].socket)

    def test_wrong_model_cross_response_and_timeout_are_rejected(self):
        for events in (
            [{'type':'response.completed','response':{'id':'bad','model':'other','status':'completed'}}],
            [{'type':'response.created','response':{'id':'one'}},{'type':'response.completed','response':{'id':'two'}}],
            []):
            class Socket:
                def send(self,payload):pass
                def recv(self,timeout):
                    if not events:raise TimeoutError
                    return json.dumps(events.pop(0))
                def close(self):pass
            self.transport.connect=lambda token:Socket()
            with self.assertRaises((gateway.ProtocolError,TimeoutError)):self.turn(self.request())

    def test_actual_websocket_frames_and_connection_close_replay(self):
        from websockets.sync.server import serve
        from websockets.sync.client import connect
        def handler(socket):
            fixture=ProviderSocket(self.reply)
            for body in socket:
                fixture.send(body)
                socket.send(fixture.recv(1));socket.send(fixture.recv(1))
        with serve(handler,'127.0.0.1',0) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            self.transport.connect=lambda token:connect('ws://127.0.0.1:'+str(server.socket.getsockname()[1]),legacy=True)
            request=self.request();result,_=self.turn(request)
            _,record=self.turn(self.continued(request,result))
            self.assertEqual(record['ws_mode'],'incremental')
            self.transport.close();server.shutdown()


if __name__=='__main__':unittest.main()
