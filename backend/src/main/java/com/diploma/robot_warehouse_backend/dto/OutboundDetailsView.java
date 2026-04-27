package com.diploma.robot_warehouse_backend.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

import java.util.List;

@Getter
@Setter
@AllArgsConstructor
public class OutboundDetailsView {
    private Integer outboundId;
    private String externalRef;
    private String status;

    private List<OutboundLineView> lines;
    private List<OutboundTaskView> tasks;
}
