Figured out a way to run this in wsl2 as well for anyone interested. It entails recompiling the wsl2 kernel with the necessary android binder flags switched on, or reusing my recompiled kernels if you prefer.

**Steps:**
- Install wsl debian (or ubuntu probably also works, using this command ```wsl.exe --install Debian```
- Inside wsl, install docker and also scrcpy; https://docs.docker.com/engine/install/debian/   Official scrcpy installation https://github.com/Genymobile/scrcpy/blob/master/install_release.sh
- Install docker desktop on your windows computer, and be sure to choose to use the "wsl2 based engine" in the general settings, as well as enabling it to start up when you sign into your computer
- 
  
