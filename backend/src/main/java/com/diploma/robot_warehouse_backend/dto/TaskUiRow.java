package com.diploma.robot_warehouse_backend.dto;

import com.diploma.robot_warehouse_backend.enums.Status;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

import java.time.LocalDateTime;

@Getter
@Setter
@AllArgsConstructor
public class TaskUiRow {
    private Integer id;
    private Status status;
    private String robotId;
    private String sku;
    private String manufacturer;
    private String targetShelfCode;
    private String targetSide;
    private String targetLevel;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
