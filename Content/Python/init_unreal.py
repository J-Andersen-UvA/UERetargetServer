import IKRetargeterServer
import unreal

retargeter = IKRetargeterServer.Retargeter()
retargeter.start()

# Keep the program running until user interrupts or signals to stop
try:
    while True:
        # Keep the main thread alive
        unreal.idle()
except KeyboardInterrupt:
    retargeter.stop()
