# RobotStatus.msg - 핑키 및 로봇팔 실시간 상태 메시지
builtin_interfaces/Time timestamp
string robot_id                  # "pinky_1", "pinky_2", "pinky_3", "omx_1", "omx_2", "omx_3"
string state                     # "IDLE", "NAVIGATING", "LOADING", "UNLOADING", "RECOVERING", "HOLD", "ERROR"
geometry_msgs/Pose current_pose
float32 battery_percentage
bool is_emergency_stopped
string current_task_id
