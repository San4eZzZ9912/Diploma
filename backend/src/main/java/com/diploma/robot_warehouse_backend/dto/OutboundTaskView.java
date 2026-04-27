package com.diploma.robot_warehouse_backend.dto;

import com.diploma.robot_warehouse_backend.enums.Status;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;


@Getter
@Setter
@AllArgsConstructor
public class OutboundTaskView {
    private Integer taskId;
    private String productName;
    private String sku;
    private String manufacturer;
    private Status status;
}
