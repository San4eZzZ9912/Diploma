package com.diploma.robot_warehouse_backend.dto;

import com.diploma.robot_warehouse_backend.enums.Level;
import com.diploma.robot_warehouse_backend.enums.Side;
import com.diploma.robot_warehouse_backend.enums.Type;

public record DeliveryTaskResponse(
        Integer taskId,
        Type type,

        String sku,
        String manufacturer,

        Integer sourceSlotId,
        String sourceShelfCode,
        Level sourceLevel,
        Side sourceSide,
        Integer sourceApriltagId,
        Double sourceX,
        Double sourceY,
        Double sourceYaw,

        Integer targetSlotId,
        String deliveryShelfCode,
        Level targetLevel,
        Side targetSide,
        Integer targetApriltagId,
        Double targetX,
        Double targetY,
        Double targetYaw
) {
}
