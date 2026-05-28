package com.diploma.robot_warehouse_backend.dto;

import com.diploma.robot_warehouse_backend.enums.Level;
import com.diploma.robot_warehouse_backend.enums.Side;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.enums.Type;
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
    private Type type;
    private String robotId;
    private String sku;
    private String manufacturer;
    private String targetShelfCode;
    private Side targetSide;
    private Level targetLevel;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
