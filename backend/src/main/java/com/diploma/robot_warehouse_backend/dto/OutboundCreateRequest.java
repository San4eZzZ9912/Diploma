package com.diploma.robot_warehouse_backend.dto;

import lombok.Getter;
import lombok.Setter;

import java.util.List;

@Getter
@Setter
public class OutboundCreateRequest {
    private String externalRef;
    private List<OutboundItemRequest> items;
}