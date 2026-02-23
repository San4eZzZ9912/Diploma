package com.diploma.robot_warehouse_backend.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@AllArgsConstructor
public class OutboundCreateResult {
    private final Integer outboundId;
    private final int linesCreated;
    private final int tasksCreated;
}
