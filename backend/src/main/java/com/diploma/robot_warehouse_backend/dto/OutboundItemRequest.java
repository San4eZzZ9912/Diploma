package com.diploma.robot_warehouse_backend.dto;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class OutboundItemRequest {
    private Integer productId;
    private Integer quantity;
}
