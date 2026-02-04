package com.diploma.robot_warehouse_backend.dto;

import com.diploma.robot_warehouse_backend.enums.Side;
import lombok.AllArgsConstructor;
import lombok.Getter;

import java.time.LocalDateTime;

@Getter
@AllArgsConstructor
public class SlotStateResponse {
    private String shelfCode;
    private Side side;
    private boolean occupied;
    private String cubeQr;
    private LocalDateTime updatedAt;
}
