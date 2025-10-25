# inreach_mediarelay

Scripts to relay media files (video/media) received on Garmin messenger installed on e.g. waydroid &amp; raspberry pi. Other solutions are also possible here for different ways of running an android system, e.g. docker redroid is what i am currently using, which seems to be working well for this purpose. You need to install and run garmin messenger on android system/emulator of your choice, and log in with your own account or create a relay account with a valid phone number.

NOTE! **don't send multiple media attachments in one message - the messenger app does not download multiple media files, and the media file will get stuck until the next event occurs in the inbox. So - send only one media file per message**

Initially made this to bridge media sent via inreach messenger plus to my matrix chats - so that is the initial focus of my watcher script (matrix folder). Have now also created a version intended to only forward the media messages via email, for those interested in that.

**For matrix relay**

The watcher currently has a provisioning endpoint which can be used to send subscription request from a matrix room, with a media webhook url + bearer token, as well as the phone number of the garmin messenger user you want to subscribe to the media stream off. The inreach user then has to acknowledge your subscription for the watcher to start actually relaying the media by sending a text to the relay number that the watcher script will pick up.

So the flow is;
- Establish media url and token from matrix room, and request sub with a brief name and code from matrix room to provisioning API (i am making a maubot plugin to do this part automatically, but not fully there yet)
- You need to tell inreach user to send "sub <name> mini-token" to the relay number to enable subscription
- Watcher script will poll db and media folders on the waydroid/pi for new media
- When new media arrives, watcher will check phone number of sender and whether there are any active subscriptions for the number or not. If yes, it will send the file and caption to the url's it can find in the subs.json
- Afte successfull sending, watcher will delete media file

 It is possible for one inreach user to set up multiple subscriptions, meaning to send images to multiple matrix rooms. If the inreach user puts the <name> of a subscription in the first word in the caption of a media file, the file will only be sent to the specific subscription room (and not any other rooms that might be subscribing to media from the user). So multiple subscriptions and no caption = send media to all subscribed rooms

**For email relay**
- I have personally run it as a systemd-service, so the .py file, an etc/default env file and .service file for systemd is included in the email folder
- You can either run it as a bridge to a list of specific emails, then all media files will be sent to the emails listed in the env file - or you can let the sender specify email address as the first word in the caption, and it will send to the specified address (can send to multiple addresses like that as well - just separate with , or ; )
- That's it! You need to specify smtp details for an email address to send from etc in the env filde

 Probably better ways of doing this, but i am not smart enough to reverse engineer garmin's api for this - so will leave that to others!

 If you want to talk about it, feel free to contact me [on Matrix](https://matrix.to/#/#whatever:vibb.me)
