package com.diploma.robot_warehouse_backend.dto;

import com.diploma.robot_warehouse_backend.enums.Level;
import com.diploma.robot_warehouse_backend.enums.Side;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class RobotClearRequest {
    private String shelfCode; // "A" / "B"
    private Side side;        // LEFT / RIGHT
    private Level level;
    private String robotId;   // optional
}
