# inreach_mediarelay
Scripts to relay media files (video/media) received on Garmin messenger installed on waydroid &amp; raspberry pi. You need to install and run garmin messenger on the pi, and log in with your own account or create a relay account with a valid phone number.

Initially made this to bridge media sent via inreach messenger plus to my matrix chats - so that is the initial focus of my watcher script (matrix folder). Also planning to create a more standard messenger app to email version of the watcher script.

The watcher currently has a provisioning endpoint which can be used to send subscription request from a matrix room, with a media webhook url + bearer token, as well as the phone number of the garmin messenger user you want to subscribe to the media stream off. The inreach user then has to acknowledge your subscription for the watcher to start actually relaying the media by sending a text to the relay number that the watcher script will pick up.

So the flow is;
- Establish media url and token from matrix room, and request sub with a brief name and code from matrix room to provisioning API (i am making a maubot plugin to do this part automatically, but not fully there yet)
- You need to tell inreach user to send "sub <name> mini-token" to the relay number to enable subscription
- Watcher script will poll db and media folders on the waydroid/pi for new media
- When new media arrives, watcher will check phone number of sender and whether there are any active subscriptions for the number or not. If yes, it will send the file and caption to the url's it can find in the subs.json
- Afte successfull sending, watcher will delete media file

 It is possible for one inreach user to set up multiple subscriptions, meaning to send images to multiple matrix rooms. If the inreach user puts the <name> of a subscription in the first word in the caption of a media file, the file will only be sent to the specific subscription room (and not any other rooms that might be subscribing to media from the user). So multiple subscriptions and no caption = send media to all subscribed rooms

 Probably better ways of doing this, but i am not smart enough to reverse engineer garmin's api for this - so will leave that to others!

 If you want to talk about it, feel free to contact me [on Matrix](https://matrix.to/#/#whatever:vibb.me)
