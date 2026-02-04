package com.diploma.robot_warehouse_backend.dto;

import com.diploma.robot_warehouse_backend.enums.Level;
import com.diploma.robot_warehouse_backend.enums.Side;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class RobotPlaceRequest {
    private String shelfCode;
    private Side side;
    private Level level;
    private String cubeQr;
    private String robotId;
}
