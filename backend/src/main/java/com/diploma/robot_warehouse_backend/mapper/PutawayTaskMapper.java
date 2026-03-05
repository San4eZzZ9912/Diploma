package com.diploma.robot_warehouse_backend.mapper;

import com.diploma.robot_warehouse_backend.dto.PutawayTaskResponse;
import com.diploma.robot_warehouse_backend.entity.Task;
import org.mapstruct.*;

@Mapper(componentModel = MappingConstants.ComponentModel.SPRING)
public interface PutawayTaskMapper {

    @Mapping(source = "id", target = "taskId")
    @Mapping(source = "type", target = "type")

    @Mapping(source = "product.sku", target = "sku")
    @Mapping(source = "product.manufacturer", target = "manufacturer")

    @Mapping(source = "targetSlot.shelf.shelfCode", target = "targetShelfCode")
    @Mapping(source = "targetSlot.level", target = "targetLevel")
    @Mapping(source = "targetSlot.side", target = "targetSide")
    @Mapping(source = "targetSlot.apriltagId", target = "targetApriltagId")

    @Mapping(source = "targetSlot.shelf.mapX", target = "targetX")
    @Mapping(source = "targetSlot.shelf.mapY", target = "targetY")
    @Mapping(source = "targetSlot.shelf.mapYaw", target = "targetYaw")
    PutawayTaskResponse toResponse(Task task);
}
