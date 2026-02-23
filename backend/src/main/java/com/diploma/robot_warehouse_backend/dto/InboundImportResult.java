package com.diploma.robot_warehouse_backend.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@AllArgsConstructor
public class InboundImportResult {
    private Integer inboundId;
    private Integer linesCount;
    private Integer tasksCreated;
    private String fileName;
}
