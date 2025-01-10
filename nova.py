#!/usr/bin/python3

# Licensed under the 0BSD
from signal import signal, SIGINT, SIGTERM
from usb.core import find, USBTimeoutError, USBError
import pulsectl


class NovaProWireless:
    # Headset pulse name
    HEADSET_NAME = "SteelSeries_Arctis_Nova_Pro_Wireless"

    # USB IDs
    VID = 0x1038
    PID = 0x12E0

    # bInterfaceNumber
    INTERFACE = 0x4

    # bEndpointAddress
    ENDPOINT_TX = 0x4  # EP 4 OUT
    ENDPOINT_RX = 0x84  # EP 4 IN

    MSGLEN = 64  # Total USB packet is 128 bytes, data is last 64 bytes.

    # First byte controls data direction.
    TX = 0x6  # To base station.
    RX = 0x7  # From base station.

    # Second Byte
    # This is a very limited list of options, you can control way more. I just haven't implemented those options (yet)
    ## As far as I know, this only controls the icon.
    OPT_SONAR_ICON = 141
    ## Enabling this options enables the ability to switch between volume and ChatMix.
    OPT_CHATMIX_ENABLE = 73
    ## Volume controls, 1 byte
    OPT_VOLUME = 37
    ## ChatMix controls, 2 bytes show and control game and chat volume.
    OPT_CHATMIX = 69
    ## EQ controls, 2 bytes show and control which band and what value.
    OPT_EQ = 49
    ## EQ preset controls, 1 byte sets and shows enabled preset. Preset 4 is the custom preset required for OPT_EQ.
    OPT_EQ_PRESET = 46

    # PipeWire Names
    ## This is automatically detected, can be set manually by overriding this variable
    PW_ORIGINAL_SINK = None
    ## Names of virtual sound devices
    PW_GAME_SINK = "NovaGame"
    PW_CHAT_SINK = "NovaChat"

    # PipeWire virtual sink processes
    PW_LOOPBACK_GAME_MODULE_ID = None
    PW_LOOPBACK_CHAT_MODULE_ID = None

    # Keeps track of enabled features for when close() is called
    CHATMIX_CONTROLS_ENABLED = False
    SONAR_ICON_ENABLED = False

    # Stops processes when program exits
    CLOSE = False

    # Selects correct device, and makes sure we can control it
    def __init__(self):
        self.dev = find(idVendor=self.VID, idProduct=self.PID)
        if self.dev is None:
            raise ValueError("Device not found")
        if self.dev.is_kernel_driver_active(self.INTERFACE):
            self.dev.detach_kernel_driver(self.INTERFACE)

    # Takes a tuple of ints and turns it into bytes with the correct length padded with zeroes
    def _create_msgdata(self, data: tuple[int]) -> bytes:
        return bytes(data).ljust(self.MSGLEN, b"0")

    # Enables/Disables chatmix controls
    def set_chatmix_controls(self, state: bool):
        self.dev.write(
            self.ENDPOINT_TX,
            self._create_msgdata((self.TX, self.OPT_CHATMIX_ENABLE, int(state))),
        )
        self.CHATMIX_CONTROLS_ENABLED = state

    # Enables/Disables Sonar Icon
    def set_sonar_icon(self, state: bool):
        self.dev.write(
            self.ENDPOINT_TX,
            self._create_msgdata((self.TX, self.OPT_SONAR_ICON, int(state))),
        )
        self.SONAR_ICON_ENABLED = state

    # Sets Volume
    def set_volume(self, attenuation: int):
        self.dev.write(
            self.ENDPOINT_TX,
            self._create_msgdata((self.TX, self.OPT_VOLUME, attenuation)),
        )

    # Sets EQ preset
    def set_eq_preset(self, preset: int):
        self.dev.write(
            self.ENDPOINT_TX,
            self._create_msgdata((self.TX, self.OPT_EQ_PRESET, preset)),
        )

    def _detect_original_sink(self):
        """
        Finds a sink that matches the headset name and saves its full name
        """
        # If sink is set manually, skip auto detect
        if self.PW_ORIGINAL_SINK:
            return
        with pulsectl.Pulse('list-sinks') as pulse:
            sinks = pulse.sink_list()
            for sink in sinks:
                if self.HEADSET_NAME in sink.name:
                    self.PW_ORIGINAL_SINK = sink.name

    def _start_virtual_sinks(self):
        """
        Creates pulseaudio virtual combine sinks redirected to the headset.
        """
        self._detect_original_sink()
        self._remove_virtual_sinks()
        self.PW_LOOPBACK_GAME_MODULE_ID = self._create_sink(self.PW_GAME_SINK, self.PW_ORIGINAL_SINK)
        self.PW_LOOPBACK_CHAT_MODULE_ID = self._create_sink(self.PW_CHAT_SINK, self.PW_ORIGINAL_SINK)

    def _remove_virtual_sinks(self):
        """
        Removes the virtual sinks
        """
        if self.PW_LOOPBACK_GAME_MODULE_ID is not None:
            self._remove_sink(self.PW_LOOPBACK_GAME_MODULE_ID)
            self.PW_LOOPBACK_GAME_MODULE_ID = None
        if self.PW_LOOPBACK_CHAT_MODULE_ID is not None:
            self._remove_sink(self.PW_LOOPBACK_CHAT_MODULE_ID)
            self.PW_LOOPBACK_CHAT_MODULE_ID = None

    def _create_sink(self, sink_name: str, output_sink: str) -> int:
        """
        Creates a pulse module-combine-sink, and returns the module id.
        :param sink_name: the name of the sink to create
        :param output_sink: the name of the sink to redirect the output to
        :return: the virtual sink module_id
        """
        with pulsectl.Pulse('virtual-sink') as pulse:
            try:
                new_sink = pulse.module_load('module-combine-sink', f'sink_name={sink_name} slaves={output_sink} sink_properties=device.description={sink_name}')
            except pulsectl.PulseError as e:
                pulse.module_unload(new_sink)
                print(f"Failed to create sink '{sink_name}': {e}")
            return new_sink

    def _remove_sink(self, module_id: int) -> None:
        """
        Deletes the sink with the specified module_id if it exists
        :param module_id: the module_id of the sink to delete
        """
        with pulsectl.Pulse('virtual-sink') as pulse:
            for module in pulse.module_list():
                if module_id == module.index:
                    pulse.module_unload(module.index)
                    break

    def _set_sink_volume(self, module_id: int, volume: float) -> None:
        """
        Set volume for a specific sink
        :param module_id: Name of the sink
        :param volume: Volume level (0.0 to 1.0)
        """
        with pulsectl.Pulse('volume-control') as pulse:
            try:
                sinks = pulse.sink_list()
                target_sink = next((sink for sink in sinks if sink.owner_module == module_id), None)
                if target_sink:
                    pulse.volume_set_all_chans(target_sink, volume)
                else:
                    print(f"Sink '{module_id}' not found")
            except pulsectl.PulseError as e:
                print(f"Failed to set volume: {e}")

    # ChatMix implementation
    # Continuously read from base station and ignore everything but ChatMix messages (OPT_CHATMIX)
    # The .read method times out and returns an error. This error is catched and basically ignored. Timeout can be configured, but not turned off (I think).
    def chatmix(self):
        self._start_virtual_sinks()
        while not self.CLOSE:
            try:
                msg = self.dev.read(self.ENDPOINT_RX, self.MSGLEN)
                if msg[1] != self.OPT_CHATMIX:
                    continue

                # 4th and 5th byte contain ChatMix data
                gamevol = msg[2]
                chatvol = msg[3]

                # Actually change volume. Everytime you turn the dial, both volumes are set to the correct level
                self._set_sink_volume(self.PW_LOOPBACK_GAME_MODULE_ID, gamevol * 0.01)
                self._set_sink_volume(self.PW_LOOPBACK_CHAT_MODULE_ID, chatvol * 0.01)

            # Ignore timeout.
            except USBTimeoutError:
                continue
            except USBError:
                print("Device was probably disconnected, exiting..")
                self.CLOSE = True
                self._remove_virtual_sinks()
        # Remove virtual sinks on exit
        self._remove_virtual_sinks()

    # Prints output from base station. `debug` argument enables raw output.
    def print_output(self, debug: bool = False):
        while not self.CLOSE:
            try:
                msg = self.dev.read(self.ENDPOINT_RX, self.MSGLEN)
                if debug:
                    print(msg)
                match msg[1]:
                    case self.OPT_VOLUME:
                        print(f"Volume: -{msg[2]}")
                    case self.OPT_CHATMIX:
                        print(f"Game Volume: {msg[2]} - Chat Volume: {msg[3]}")
                    case self.OPT_EQ:
                        print(f"EQ: Bar: {msg[2]} - Value: {(msg[3] - 20) / 2}")
                    case self.OPT_EQ_PRESET:
                        print(f"EQ Preset: {msg[2]}")
                    case _:
                        print("Unknown Message")
            except USBTimeoutError:
                continue

    def close(self, signum=None, frame=None) -> None:
        """
        Disables activated features and cleans the created sinks
        :param signum:
        :param frame:
        """
        self.CLOSE = True
        if self.CHATMIX_CONTROLS_ENABLED:
            self.set_chatmix_controls(False)
        if self.SONAR_ICON_ENABLED:
            self.set_sonar_icon(False)

        self._remove_virtual_sinks()


# When run directly, just start the ChatMix implementation. (And activate the icon, just for fun)
if __name__ == "__main__":
    nova = NovaProWireless()
    nova.set_sonar_icon(True)
    nova.set_chatmix_controls(True)

    signal(SIGINT, nova.close)
    signal(SIGTERM, nova.close)
    try:
        nova.chatmix()
    except KeyboardInterrupt:
        nova.close()
