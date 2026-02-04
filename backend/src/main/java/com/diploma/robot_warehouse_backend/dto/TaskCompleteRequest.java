package com.diploma.robot_warehouse_backend.dto;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class TaskCompleteRequest {
    private String robotId;
    private boolean success;
    private String observedQr;
}
