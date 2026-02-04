package com.diploma.robot_warehouse_backend.dto;


import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@AllArgsConstructor
public class ShelfCoordinatesResponse {
    private String shelfCode;
    private Double mapX;
    private Double mapY;
    private Double mapYaw;
}
