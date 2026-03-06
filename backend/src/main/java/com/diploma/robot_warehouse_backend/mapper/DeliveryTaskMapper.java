package com.diploma.robot_warehouse_backend.mapper;

import com.diploma.robot_warehouse_backend.dto.DeliveryTaskResponse;
import com.diploma.robot_warehouse_backend.entity.Shelf;
import com.diploma.robot_warehouse_backend.entity.Task;
import org.mapstruct.Mapper;
import org.mapstruct.Mapping;

@Mapper(componentModel = "spring")
public interface DeliveryTaskMapper {

    @Mapping(source = "task.id", target = "taskId")
    @Mapping(source = "task.type", target = "type")
    @Mapping(source = "task.product.sku", target = "sku")
    @Mapping(source = "task.product.manufacturer", target = "manufacturer")

    @Mapping(source = "task.sourceSlot.id", target = "sourceSlotId")
    @Mapping(source = "task.sourceSlot.shelf.shelfCode", target = "sourceShelfCode")
    @Mapping(source = "task.sourceSlot.level", target = "sourceLevel")
    @Mapping(source = "task.sourceSlot.side", target = "sourceSide")
    @Mapping(source = "task.sourceSlot.apriltagId", target = "sourceApriltagId")
    @Mapping(source = "task.sourceSlot.shelf.mapX", target = "sourceX")
    @Mapping(source = "task.sourceSlot.shelf.mapY", target = "sourceY")
    @Mapping(source = "task.sourceSlot.shelf.mapYaw", target = "sourceYaw")

    @Mapping(source = "task.targetSlot.id", target = "targetSlotId")
    @Mapping(source = "task.targetSlot.shelf.shelfCode", target = "deliveryShelfCode")
    @Mapping(source = "task.targetSlot.level", target = "targetLevel")
    @Mapping(source = "task.targetSlot.side", target = "targetSide")
    @Mapping(source = "task.targetSlot.apriltagId", target = "targetApriltagId")

    @Mapping(source = "deliveryShelf.mapX", target = "targetX")
    @Mapping(source = "deliveryShelf.mapY", target = "targetY")
    @Mapping(source = "deliveryShelf.mapYaw", target = "targetYaw")
    DeliveryTaskResponse toResponse(Task task, Shelf deliveryShelf);
}
