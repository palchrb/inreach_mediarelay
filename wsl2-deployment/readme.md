Figured out a way to run this in wsl2 as well for anyone interested. It entails recompiling the wsl2 kernel with the necessary android binder flags switched on, or reusing my recompiled kernels if you prefer.

**Steps:**
- Install wsl debian (or ubuntu probably also works, using this command in e.g. powershell ```wsl.exe --install Debian```
- Inside wsl, install docker and also scrcpy; https://docs.docker.com/engine/install/debian/   Official scrcpy installation https://github.com/Genymobile/scrcpy/blob/master/install_release.sh
- Install docker desktop on your windows computer, and be sure to choose to use the "wsl2 based engine" in the general settings, as well as enabling it to start up when you sign into your computer
- Either you recompile and make your own wsl2 kernel + modules per these instructions https://gist.github.com/onomatopellan/c5220c0efddaff69aaff77cca80b7b8e - or you can download them from the wsl-kernel folder on my repo. Then open wsl settings from the windows start menu, go to developer settings and select the  bzImage file as custom kernel, and the .vhdx file as custom kernel modules. Then you should run ```wsl --shutdown``` and restart wsl with the ```wsl``` command from powershell
- Inside wsl run ```nano /etc/wsl.conf``` and add below the [boot] section add
  
  ```command="mkdir -p /dev/binderfs && mount -t binder binder /dev/binderfs && modprobe vgem"```
- Restart wsl again as above
- Clone the wsl2-deployment/redroid subfolder into your wsl2 debian installation
- Inside the redroid  folder, run ´´´docker compose build´´´ ´´´and docker-compose up -d´´´
- Initial startup now could take up to 5 minutes, and it will also do after each reboot (or wsl --shutdown). Not sure why.. But ultimately it should start up. Then run ´´´adb connect localhost:5555´´´ and check that the device shows up as "device" and not offline when running ´´´adb devices´´´. If it says offline, then wait a few minutes more and retry.
- Assuming scrcpy is successfully installed, run scrcpy -s localhost:5555, and the redroid phone gui should pop up!
- Now you need to register the device with google, just follow this procedure here while connected to adb https://www.google.com/android/uncertified. It could then take up to an hour before your device knows it has been register. You might need to run ´´´docker compose down && docker compose up -d´´´ to restart the unit for it to complete registration. After restarting device, you also need to restart scrcpy
- Once it is registered,  you can login to the google play store, and successfully download the Garmin Messenger app. Log in to the app with the phone number you intend to use as media relay bridge
- Then we can focus on getting the bridge to be correcly set up. From wsl and the folder where the docker compose file is, you should run ```nano bridge/garmin.env``` and customize the settings you want to use for sending the media files via email. They are the same as described in the main readme for this repo.
- Once this is in place, you should run another restart of the containers with ´´´docker compose down && docker compose up -d´´´
- Et voila, it should now work! You can check ´´´docker logs garmin-bridge -f´´´ to see whether media is identified and successfully sent

Note, there might be dependencies i have not covered here that would need to be installed. If you are unable to understand how to do so I propose you ask chatgpt or a friend.
