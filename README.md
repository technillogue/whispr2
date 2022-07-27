<img src="https://raw.githubusercontent.com/technillogue/whispr/main/whispr_avatar.png" alt="drawing" width="100"/>

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) 

# whispr

a [signal](https://signal.org/en/download/) bot that runs a little social media. use commands to follow other users or invite them to follow you. messages to whisprbot that don't start with `/` are posts, and will be sent to your followers. unlike a group chat, your followers cannot see who else follows you, and have fine-grained control over who to get messages from. use `/help` for on-line documentation.

to use the public server, send a signal message to [+12692304655](https://signal.me/#p/+12692304655)

## installation 

see <https://github.com/mobilecoinofficial/forest>

whispr launches a patched [signal-cli](https://github.com/technillogue/signal-cli) subprocess to receive and send messages that uses stdin/stdout instead of the upstream DBus protocol. you must build it to run a server yourself. at some point it'll be possible to download a distribution tarball, but that doesn't seem to work yet. 

```sh
git clone https://github.com/technillogue/signal-cli
cd signal-cli
./gradlew build
./gradlew installDist
ln -s signal-cli/build/install/signal-cli/bin/signal-cli ../signal-cli-script
```

you need a phone number that is not already registered with signal. you can use google voice or twilio for this. all phone numbers must include a + country code and no other formatting.

```sh
echo "your phone number" > number # also used by whispr.py
./signal-cli-script -u `cat number` register
./signal-cli-script -u `cat number` verify <verification code from signal>
```

finally, run `poetry install` (and `pip3 install poetry` if you haven't already).
