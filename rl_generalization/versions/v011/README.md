# v011: stationary rectangular robot and circular tray

User confirms robot stays parked. Chassis is a fixed box, tray a disk with 64 separate collision walls retaining an open interior. Diameter 11.5cm read from annotated photo (outer diameter assumed); floor height14cm user-reported, interpreted as tray inner floor above room floor. Rim height0.8cm/thickness0.3cm, chassis9x10cm and parking transform are provisional. Raw annotation values and placement reasoning are in configs/mobile_layout.json. Dish curvature is approximated by flat floor/vertical walls; no navigation dynamics.

Box and lid remain independent rigid bodies from v010 (detachable lid still assumed). Canvas/cardboard compliance and task controllers are not implemented. Tray contact solref0.005/1 and solimp0.99/0.99/0.001 are numerical assumptions, not material calibration. Centered box passive drop settles within1mm of tray floor without warnings. Settling sweeps are NOT robot loading or RL training.

Build from a v010 generated scene using code/replace_mobile.py SOURCE NEW_OUTPUT configs/mobile_layout.json. Portable archive contains scene assets and upstream license, check.py, run_remote.sh and requirements.txt. Run bash run_remote.sh for900 short settling trials. CURRENT staysv004. Use a new tmux session to avoid disturbing existing jobs.
