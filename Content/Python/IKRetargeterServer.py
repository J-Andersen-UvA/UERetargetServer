import unreal
import socket
import threading
import ikRigCreator
import IKRetargeter
import simpleQueue
import skeletalMeshImporter
import fetchUEInfo
import animationImporter
import animationExporter
import receiveFile
import functools
import os
import websockets
import asyncio

class Retargeter:
    """
    The Retargeter class manages a server for handling Unreal Engine animation retargeting tasks.
    It includes methods to start and stop the server, process client requests, and perform various retargeting and import operations.
    The class uses a queue to manage tasks, ensuring they are executed in the main thread via a Slate post-tick callback.

    Attributes:
        socket: The server socket for listening to client connections.
        running: A flag indicating whether the server is running.
        slate_post_tick_handle: Handle for the Slate post-tick callback.
        queue: A queue to manage tasks to be processed.
        current_connection: The current client connection being processed.
        rigs: A list to store fetched IK rigs.
        retargets: A list to store fetched retargeters.

    Methods:
        start(port=9999): Starts the server and begins listening for client connections.
        stop(): Stops the server and closes the socket.
        on_slate_post_tick(delta_time): Processes tasks from the queue in the main thread.
        import_fbx(args): Enqueues an FBX import task.
        import_fbx_animation(args): Enqueues an FBX animation import task.
        create_ik_rig(mesh_name): Enqueues a task to create an IK rig.
        retarget_ik_rigs(args): Enqueues a task to retarget IK rigs.
        fetch_ik_rigs(args): Enqueues a task to fetch IK rigs.
        fetch_retargets(args): Enqueues a task to fetch IK retargeters.
        asset_exists(asset_path): Enqueues a task to check if an asset exists.
        retarget_animation(args): Enqueues a task to retarget an animation.
        close_server(): Closes the server socket.
        handle_default(data): Handles default messages.
        handle_data(data, connection): Handles data received from clients and dispatches tasks.
        listen_clients(): Listens for client connections and processes incoming data.
        send_response(connection, message): Sends a response to the client.
        tick(delta_time): Placeholder for future implementation.
    """
    def __init__(self):
        self.socket = None
        self.running = False
        self.slate_post_tick_handle = None
        self.queue = simpleQueue.Queue()
        self.current_connection = None
        self.rigs = []
        self.retargets = []
        self.ports = {8071: True, 8072: True, 8073: True}
        self.lock = threading.Lock()
        self.export_path = "C:/Users/VICON/Desktop/tmp/testAnimExport/"  # Replace with your desired export path
        self.import_path = "C:/Users/VICON/Desktop/tmp/testImport/"  # Replace with your desired import path

        # Check if running inside Docker
        if os.path.exists("/.dockerenv"):
            self.export_path = "/usr/src/your_project/exports/"  # Update with Docker export path
            self.import_path = "/usr/src/your_project/imports/"  # Update with Docker import path
        
        self.thread_local = threading.local()


    def start(self, host="0.0.0.0", port=8070):
        self.running = True
        self.thread_local.serverType = "TCP"

        # Start the server socket in a separate thread
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((host, port))
        self.socket.listen(1)
        print("Retargeter started. Listening on port", port)
        
        # Register Slate post-tick callback
        self.slate_post_tick_handle = unreal.register_slate_post_tick_callback(self.on_slate_post_tick)

        # Start listening for clients in a separate daemon thread
        listen_thread = threading.Thread(target=self.listen_clients, daemon=True)
        listen_thread.start()
        websockets_thread = threading.Thread(target=self.start_websocket_server, daemon=True)
        websockets_thread.start()

    def stop(self):
        self.running = False
        # Close the server socket
        if self.socket:
            self.socket.close()
            self.socket = None  # Set socket to None after closing
        print("Retargeter stopped.")
        
        # Unregister Slate post-tick callback
        if self.slate_post_tick_handle:
            unreal.unregister_slate_post_tick_callback(self.slate_post_tick_handle)
    
    def on_slate_post_tick(self, delta_time):
        """
        Processes functions from the queue and executes them with the provided arguments. Logs the function name, arguments, and result.
        We do this in the Slate post-tick callback to ensure that we are executing the queue functions in the main thread.
        For each function we send a response back to the client with the result of the function.
        Depending on the incomming function we handle the function calls differently.

        Args:
            delta_time: The time elapsed since the last tick (currently not used)

        return:
            None
        """
        if (self.queue.size() > 0):
            # Dequeue the item from the queue
            dequeued_item = self.queue.dequeue()

            if isinstance(dequeued_item, simpleQueue.QueueItem):
                func = dequeued_item.func
                args = dequeued_item.args
                connection = dequeued_item.connection
                self.thread_local.serverType = dequeued_item.connection_type
                print("Server type:", self.thread_local.serverType)
                unreal.log(f"Calling function {func.__name__} with arguments: {args}")
            else:
                # Handle unexpected case where dequeued_item is not an instance of QueueItem
                unreal.log_error("Unexpected item type returned from queue.dequeue()")

            if func == fetchUEInfo.fetch_ik_rigs:
                result = func(args)
                self.rigs = result
            elif func == fetchUEInfo.fetch_retargets:
                result = func(args)
                self.retargets = result
            elif func == IKRetargeter.retarget_animations:
                result = func(args)
            elif func == animationExporter.export_animation:
                result = func(*args)
                self.send_file(result[1], connection)
                # return
            elif func == self.rig_retarget_send:
                args = args[0].split(',')
                result = func(*args)
            else:
                result = func(*args)

            unreal.log("Result: " + str(result))
            if func != animationExporter.export_animation and func != self.rig_retarget_send:
                print("func name: ", func.__name__)
                print("Sending response and closing connection...")
                self.send_response(self.current_connection, str(result))
        pass
    
    def import_fbx(self, args):
        args = args.split(',')

        if len(args) < 1:
            self.send_response(self.current_connection, "Invalid message format, missing arguments. Expecting: fbx_file_path, destination_path (optional)")
            raise ValueError("Invalid message format, missing arguments. Expecting: fbx_file_path, destination_path (optional)")

        # Import FBX file into Unreal Engine
        print("Importing FBX file:", args[0])

        if len(args) > 1:
            self.queue.enqueue(skeletalMeshImporter.import_fbx, [args[0], args[1]], connection_type=self.fetch_server_type())
        else:
            self.queue.enqueue(skeletalMeshImporter.import_fbx, [args[0]], connection_type=self.fetch_server_type())

    def import_fbx_animation(self, args):
        args = args.split(',')

        if len(args) < 3:
            self.send_response(self.current_connection, "Invalid message format, missing arguments. Expecting: fbx_file_path, destination_path, name, skeleton_path (optional)")
            raise ValueError("Invalid message format, missing arguments. Expecting: fbx_file_path, destination_path, name, skeleton_path (optional)")

        # Import FBX animation file into Unreal Engine
        print("Importing FBX animation file:", args[0])
        self.queue.enqueue(animationImporter.import_fbx_animation, args, connection_type=self.fetch_server_type())

    def create_ik_rig(self, mesh_name):
        # Create IK rig for the given mesh
        print("Going to create IK Rig for:", mesh_name)
        self.queue.enqueue(ikRigCreator.createIKRig, [mesh_name], connection_type=self.fetch_server_type())

    def retarget_ik_rigs(self, args):
        args = args.split(',')
        if len(args) < 3:
            self.send_response(self.current_connection, "Invalid message format, missing arguments. Expecting: source_rig_path, target_rig_path, rtg_name")
            raise ValueError("Invalid message format, missing arguments. Expecting: source_rig_path, target_rig_path, rtg_name")

        source_rig_path = args[0]
        target_rig_path = args[1]
        rtg_name = args[2]

        print("Retargeting IK rigs:", source_rig_path, target_rig_path)
        self.queue.enqueue(IKRetargeter.create_retargeter, [source_rig_path, target_rig_path, rtg_name], connection_type=self.fetch_server_type())

    def fetch_ik_rigs(self, args):
        args = args.split(',')
        if len(args) < 1:
            self.send_response(self.current_connection, "Invalid message format, missing arguments. Expecting: paths to folders to be searched for IK rigs.")
            raise ValueError("Invalid message format, missing arguments. Expecting: paths to folders to be searched for IK rigs.")

        print("Fetching IK rigs")
        print(args)
        self.queue.enqueue(fetchUEInfo.fetch_ik_rigs, args, connection_type=self.fetch_server_type())

    def fetch_retargets(self, args):
        args = args.split(',')
        if len(args) < 1:
            self.send_response(self.current_connection, "Invalid message format, missing arguments. Expecting: paths to folders to be searched for IK retargeters.")
            raise ValueError("Invalid message format, missing arguments. Expecting: paths to folders to be searched for IK retargeters.")

        print("Fetching IK retargeters")
        print(args)
        self.queue.enqueue(fetchUEInfo.fetch_retargets, args, connection_type=self.fetch_server_type())

    # Function to check if an asset exists
    def asset_exists(self, asset_path):
        self.queue.enqueue(unreal.EditorAssetLibrary.does_asset_exist, [asset_path], connection_type=self.fetch_server_type())

    def retarget_animation(self, args):
        args = args.split(',', 1)
        if len(args) < 2:
            self.send_response(self.current_connection, "Invalid message format, missing arguments. Expecting: retargeter_path, animation_paths")
            raise ValueError("Invalid message format, missing arguments. Expecting: retargeter_path, animation_paths")

        retargeter_path = args[0]
        animation_path = args[1]

        print("Retargeting animation:", retargeter_path, animation_path)
        self.queue.enqueue(IKRetargeter.retarget_animations, [retargeter_path, animation_path], connection_type=self.fetch_server_type())

    def export_fbx_animation(self, args):
        if not isinstance(args, list):
            args = args.split(',')

        if len(args) < 2:
            self.send_response(self.current_connection, "Invalid message format, missing arguments. Expecting: animation_asset_path, export_path, name(optional), ascii(optional), force_front_x_axis(optional)")
            raise ValueError("Invalid message format, missing arguments. Expecting: animation_asset_path, export_path, name(optional), ascii(optional), force_front_x_axis(optional)")

        print("Exporting animation to FBX:", args[0], args[1])
        self.queue.enqueue(animationExporter.export_animation, args, connection=self.current_connection, connection_type=self.fetch_server_type())

    def receive_fbx(self, filename, connection=None):
        if connection is None:
            connection = self.current_connection

        print("Received filename:", filename)

        # Check if we are already processing a file in this thread
        receive_thread = threading.Thread(target=self.handle_fbx_receive, args=(connection, filename))
        receive_thread.start()

    def handle_fbx_receive(self, connection, filename, host='0.0.0.0'):
        self.thread_local.serverType = "TCP"

        port = self.get_free_port()
        if port is None:
            self.send_response(connection, "No available port for file transfer.")
            return

        server_sock = receiveFile.open_listen_socket(host, port)
        self.send_response(connection, f"Listening for file on {port}")
        receiveFile.receive_file(filepath=(self.import_path + filename), server_socket=server_sock)

        # Release port
        with self.lock:
            self.ports[port] = True
        print(f"Port {port} released.")
    
    def get_free_port(self, start_port=8071):
        with self.lock:
            for port in range(start_port, start_port + len(self.ports)):
                if self.ports.get(port):
                    # Set the port to be in use
                    self.ports[port] = False
                    print(f"Port {port} allocated.")
                    return port
            print("No free port found.")
            return None

    def rig_retarget_send_queue(self, args):
        self.queue.enqueue(self.rig_retarget_send, [args], connection_type=self.fetch_server_type())

    def rig_retarget_send(self, source_mesh_path, target_mesh_path, animation_path):
        # TODO: Test this function
        if source_mesh_path == "" or target_mesh_path == "" or animation_path == "":
            self.send_response(self.current_connection, "Invalid message format, missing argument(s). Expecting: source_mesh_path, target_mesh_path, animation_path")
            raise ValueError("Invalid message format, missing argument(s). Expecting: source_mesh_path, target_mesh_path, animation_path")

        print("Retargeting IK rigs:", source_mesh_path, target_mesh_path)
        source_rig_name = source_mesh_path.split('/')[-1]
        target_rig_name = target_mesh_path.split('/')[-1]
        retargeter_name = f"RTG_{source_rig_name}_to_{target_rig_name}"
        animation_name = animation_path.split('/')[-1]

        # Check if the source and target rigs exist, if not create them
        source_rig_path = fetchUEInfo.fetch_rig_with_name(source_rig_name, "/Game/IKRigs")
        target_rig_path = fetchUEInfo.fetch_rig_with_name(target_rig_name, "/Game/IKRigs")
        if not source_rig_path:
            print("Creating source rig:", source_mesh_path)
            ikRigCreator.createIKRig(source_rig_name)
            source_rig_path = fetchUEInfo.fetch_rig_with_name(source_rig_name, "/Game/IKRigs")
        if not target_rig_path:
            print("Creating target rig:", target_mesh_path)
            target_rig_path = ikRigCreator.createIKRig(target_rig_name)
            target_rig_path = fetchUEInfo.fetch_rig_with_name(target_rig_name, "/Game/IKRigs")

        retarget_path = fetchUEInfo.fetch_retargets_with_name(retargeter_name, "/Game/Retargets")
        # Check if the retargeter already exists
        if not retarget_path:
            print("Creating retargeter:", source_rig_path, target_rig_path, retargeter_name)
            if not IKRetargeter.create_retargeter(source_rig_path, target_rig_path, retargeter_name):
                raise ValueError(f"Failed to create retargeter at path /Game/Retargets/{retargeter_name}")
            retarget_path = fetchUEInfo.fetch_retargets_with_name(retargeter_name, "/Game/Retargets")

        IKRetargeter.retarget_animations(retarget_path, animation_path)
        self.export_fbx_animation([animation_path, self.export_path, f"{animation_name}_{source_rig_name}_to_{target_rig_name}"])

    def fetch_files(self, folder_path):
        # Fetch all files in the specified folder
        print("Fetching files in folder:", folder_path)
        self.queue.enqueue(fetchUEInfo.fetch_all_assets_in_path, [folder_path], connection_type=self.fetch_server_type())

    def download_from_url(self, url, destination_path=""):
        if url == "":
            self.send_response(self.current_connection, "Invalid message format, missing argument(s). Expecting: url, destination_path (optional)")
            raise ValueError("Invalid message format, missing argument(s). Expecting: url, destination_path (optional)")

        if destination_path == "":
            destination_path = self.import_path

        print(f"Downloading file from URL: {url}")
        file_name = url.split('/')[-1]
        if receiveFile.download_file_from_url(url, destination_path + file_name):
            self.send_response(self.current_connection, f"File downloaded successfully path({destination_path + file_name}).")
        else:
            self.send_response(self.current_connection, "Failed to download file.")

    def close_server(self):
        # Close the server socket
        if self.socket:
            self.socket.close()
            self.socket = None

    def handle_default(self, data):
        # Handle default message
        print("(Default) Received message:", data)
        self.send_response(self.current_connection, "(Default) Received message: " + data)
    
    def send_file(self, filepath, connection=None):
        if connection is None:
            connection = self.current_connection
        try:
            with open(filepath, 'rb') as file:
                data = file.read()
                connection.sendall(data)
            print(f"Sent file: {filepath} to {connection}")
            connection.sendall(b"EOF")
        except Exception as e:
            print(f"Failed to send file: {e}")
            raise e
        finally:
            # self.send_response(connection, f"File sent: {filepath}")
            connection.close()

    def handle_data(self, data, connection):
        # Handle data received from client
        try:
            # Decode the byte string into a regular string
            if self.fetch_server_type() != "WebSocket":
                data_str = data.decode('utf-8')
                print(f"Decoded data: {data_str}")
                data = data_str

            # Split the decoded string into parts
            parts = data.split(':', 1)
            if len(parts) < 2:
                self.send_response(connection, "Invalid message format, missing ':'")
                raise ValueError("Invalid message format, missing ':'")

            message_type = parts[0]
            message_content = parts[1]
            self.current_connection = connection

            print(f"Message type: {message_type}")
            print(f"Message content: {message_content}")
            if self.fetch_server_type() != "WebSocket":
                print(f"Client: {self.current_connection}")

            # Define message handlers
            message_handlers = {
                "create_ik_rig": self.create_ik_rig,
                "asset_exists": self.asset_exists,
                "import_fbx": self.import_fbx,
                "import_fbx_animation": self.import_fbx_animation,
                "import_fbx_from_url": self.download_from_url,
                "retarget_ik_rigs": self.retarget_ik_rigs,
                "fetch_ik_rigs": self.fetch_ik_rigs,
                "fetch_retargets": self.fetch_retargets,
                "retarget_animation": self.retarget_animation,
                "close_server": self.close_server,
                "stop_server": self.stop,
                "export_fbx_animation": self.export_fbx_animation,
                "export_animation": self.export_fbx_animation,
                "send_file": self.send_file,
                "rig_retarget_send": self.rig_retarget_send_queue,
                "receive_fbx": functools.partial(self.receive_fbx, connection=connection),
                "fetch_files": self.fetch_files,  # Add fetch_files handler
            }

            # Call the appropriate handler based on the message type
            handler = message_handlers.get(message_type, self.handle_default)

            if message_content == "" or message_content == None:
                handler()
            else:
                handler(message_content)

            # Send a response to the client
            # self.send_response(connection, f"Processed {message_type}")

        except UnicodeDecodeError as e:
            # Handle decoding errors
            print(f"Error decoding data: {e}")
            self.send_response(connection, f"Error decoding data: {e}")
        except ValueError as ve:
            # Handle invalid message format errors
            print(f"Error: {ve}")
            self.send_response(connection, f"Error: {ve}")
        except Exception as e:
            # Handle any other unexpected errors
            print(f"Unexpected error: {e}")
            self.send_response(connection, f"Unexpected error: {e}")


    def listen_clients(self):
        """
        The method listens for client connections and handles them in separate threads.
        Especially for the file transfer we need to be able to handle multiple connections at the same time.
        """
        self.thread_local.serverType = "TCP"

        while self.running and self.socket:
            try:
                connection, client_address = self.socket.accept()
                print('Connection from', client_address)
                
                # In order to start a new thread later on, we need to communicate with current connections
                # in a thread-safe way.
                client_thread = threading.Thread(target=self.client_handler, args=(connection,))
                client_thread.start()
                
            except Exception as e:
                if self.socket:
                    print("Error accepting connection:", e)
                break

    def client_handler(self, connection):
        """
        This method handles client data.
        """
        self.thread_local.serverType = "TCP"

        try:
            while True:
                data = connection.recv(1024)
                if data:
                    self.handle_data(data, connection)
                else:
                    break
        except Exception as e:
            print("Error in client handler:", e)
        # finally:
        #     connection.close()

    # We will use this method to handle WebSocket data
    def start_websocket_server(self, host="0.0.0.0", port=8069):
        self.thread_local.serverType = "WebSocket"

        def run_server():
            self.thread_local.serverType = "WebSocket"

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def handle_websocket(websocket, path):
                try:
                    async for message in websocket:
                        await self.handle_websocket_data(message, websocket)
                except Exception as e:
                    print(f"Error in WebSocket handler: {e}")

            async def start_server():
                server = await websockets.serve(handle_websocket, host, port)
                print(f"WebSocket server listening on ws://{host}:{port}")

                # Keep the server running until the thread is stopped
                await server.wait_closed()

            # Run the asyncio event loop
            loop.run_until_complete(start_server())
            loop.run_forever()

        # Start the server in a new thread
        server_thread = threading.Thread(target=run_server)
        server_thread.start()
        print(f"WebSocket server listening on ws://{host}:{port}")

    async def handle_websocket_data(self, data, websocket):
        try:
            # Handle WebSocket data here
            print(f"Received WebSocket data: {data}")
            self.handle_data(data, websocket)
            await websocket.send("Received WebSocket data")
        except Exception as e:
            print(f"Error handling WebSocket data: {e}")

    async def send_response_websocket(self, websocket, message, no_close=False):
        try:
            await websocket.send(message)
            if not no_close:
                await websocket.close()
        except Exception as e:
            print(f"Error sending response: {e}")

    def send_response(self, connection, message, no_close=False):
        if self.fetch_server_type() == "WebSocket":
            asyncio.run(self.send_response_websocket(connection, message, no_close))
            return

        try:
            connection.sendall(message.encode('utf-8'))
        except Exception as e:
            print(f"Error sending response: {e}")
        finally:
            if not no_close:
                print("Closing connection")
                connection.close()

    def tick(self, delta_time):
        pass

    def fetch_server_type(self):
        print("Fetching server type...")
        server_type = getattr(self.thread_local, 'serverType', None)
        print("Server type:", server_type)
        return server_type



# Example usage
retargeter = Retargeter()
retargeter.start()

# Keep the program running until user interrupts or signals to stop
try:
    while True:
        # Keep the main thread alive
        unreal.idle()
except KeyboardInterrupt:
    retargeter.stop()
