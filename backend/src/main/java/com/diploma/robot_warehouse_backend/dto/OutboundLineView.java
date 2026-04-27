package com.diploma.robot_warehouse_backend.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@AllArgsConstructor
public class OutboundLineView {
    private Integer lineId;
    private String productName;
    private String sku;
    private String manufacturer;
    private Integer quantity;
}
