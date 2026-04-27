package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.NavPoseResponse;
import com.diploma.robot_warehouse_backend.entity.Shelf;
import com.diploma.robot_warehouse_backend.entity.ShelfSlot;
import com.diploma.robot_warehouse_backend.entity.Task;
import com.diploma.robot_warehouse_backend.enums.Role;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.enums.Type;
import com.diploma.robot_warehouse_backend.repository.ShelfRepository;
import com.diploma.robot_warehouse_backend.repository.TaskRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class RobotNavServiceTest {

    @Mock
    private ShelfRepository shelfRepository;

    @Mock
    private TaskRepository taskRepository;

    @InjectMocks
    private RobotNavService robotNavService;

    @Test
    @DisplayName("getPickPose: для DELIVERY-задачи должен вернуть координаты source shelf")
    void getPickPose_shouldReturnSourceShelfPoseForDeliveryTask() {
        Shelf sourceShelf = shelf(1, "STORAGE-A", Role.STORAGE, 1.0, 2.0, 0.5);
        ShelfSlot sourceSlot = slot(10, sourceShelf);
        Task task = task(100, Type.DELIVERY, Status.IN_PROGRESS, "robot-1", sourceSlot, null);

        when(taskRepository.findFirstByRobotIdAndStatus("robot-1", Status.IN_PROGRESS))
                .thenReturn(Optional.of(task));

        NavPoseResponse result = robotNavService.getPickPose("robot-1");

        assertPose(result, 1.0, 2.0, 0.5);
        verify(taskRepository).findFirstByRobotIdAndStatus("robot-1", Status.IN_PROGRESS);
        verifyNoInteractions(shelfRepository);
    }

    @Test
    @DisplayName("getPickPose: если DELIVERY-задачи нет, должен вернуть координаты PICK shelf")
    void getPickPose_shouldReturnPickShelfWhenNoInProgressDeliveryTask() {
        Shelf pickShelf = shelf(2, "PICK-01", Role.PICK, 10.0, 20.0, 1.57);

        when(taskRepository.findFirstByRobotIdAndStatus("robot-1", Status.IN_PROGRESS))
                .thenReturn(Optional.empty());
        when(shelfRepository.findFirstByRole(Role.PICK))
                .thenReturn(Optional.of(pickShelf));

        NavPoseResponse result = robotNavService.getPickPose("robot-1");

        assertPose(result, 10.0, 20.0, 1.57);
        verify(taskRepository).findFirstByRobotIdAndStatus("robot-1", Status.IN_PROGRESS);
        verify(shelfRepository).findFirstByRole(Role.PICK);
    }

    @Test
    @DisplayName("getPlacePose: если IN_PROGRESS задачи нет, должен вернуть Optional.empty")
    void getPlacePose_shouldReturnEmptyWhenNoTask() {
        when(taskRepository.findFirstByRobotIdAndStatus("robot-1", Status.IN_PROGRESS))
                .thenReturn(Optional.empty());

        Optional<NavPoseResponse> result = robotNavService.getPlacePose("robot-1");

        assertTrue(result.isEmpty());
        verify(taskRepository).findFirstByRobotIdAndStatus("robot-1", Status.IN_PROGRESS);
        verifyNoInteractions(shelfRepository);
    }

    @Test
    @DisplayName("getPlacePose: для DELIVERY-задачи должен вернуть координаты DELIVERY shelf")
    void getPlacePose_shouldReturnDeliveryShelfForDeliveryTask() {
        Shelf deliveryShelf = shelf(3, "DELIVERY-01", Role.DELIVERY, 7.0, 8.0, 0.0);
        Task task = task(101, Type.DELIVERY, Status.IN_PROGRESS, "robot-1", null, null);

        when(taskRepository.findFirstByRobotIdAndStatus("robot-1", Status.IN_PROGRESS))
                .thenReturn(Optional.of(task));
        when(shelfRepository.findFirstByRole(Role.DELIVERY))
                .thenReturn(Optional.of(deliveryShelf));

        Optional<NavPoseResponse> result = robotNavService.getPlacePose("robot-1");

        assertTrue(result.isPresent());
        assertPose(result.get(), 7.0, 8.0, 0.0);

        verify(taskRepository).findFirstByRobotIdAndStatus("robot-1", Status.IN_PROGRESS);
        verify(shelfRepository).findFirstByRole(Role.DELIVERY);
    }

    @Test
    @DisplayName("getPlacePose: для не-DELIVERY задачи должен вернуть координаты target shelf")
    void getPlacePose_shouldReturnTargetShelfForPutawayTask() {
        Shelf targetShelf = shelf(4, "STORAGE-B", Role.STORAGE, 3.5, 4.5, 1.0);
        ShelfSlot targetSlot = slot(20, targetShelf);
        Task task = task(102, Type.PUTAWAY, Status.IN_PROGRESS, "robot-1", null, targetSlot);

        when(taskRepository.findFirstByRobotIdAndStatus("robot-1", Status.IN_PROGRESS))
                .thenReturn(Optional.of(task));

        Optional<NavPoseResponse> result = robotNavService.getPlacePose("robot-1");

        assertTrue(result.isPresent());
        assertPose(result.get(), 3.5, 4.5, 1.0);

        verify(taskRepository).findFirstByRobotIdAndStatus("robot-1", Status.IN_PROGRESS);
        verifyNoInteractions(shelfRepository);
    }

    @Test
    @DisplayName("getPlacePose: если у IN_PROGRESS задачи нет targetSlot, должен выбросить исключение")
    void getPlacePose_shouldThrowWhenTargetSlotIsNull() {
        Task task = task(103, Type.PUTAWAY, Status.IN_PROGRESS, "robot-1", null, null);

        when(taskRepository.findFirstByRobotIdAndStatus("robot-1", Status.IN_PROGRESS))
                .thenReturn(Optional.of(task));

        IllegalStateException ex = assertThrows(
                IllegalStateException.class,
                () -> robotNavService.getPlacePose("robot-1")
        );

        assertTrue(ex.getMessage().contains("has no target_slot_id"));
    }

    @Test
    @DisplayName("getPickPose: если у shelf нет map-координат, должен выбросить исключение")
    void getPickPose_shouldThrowWhenShelfCoordinatesAreNull() {
        Shelf pickShelf = shelf(5, "PICK-02", Role.PICK, null, 2.0, 0.0);

        when(taskRepository.findFirstByRobotIdAndStatus("robot-1", Status.IN_PROGRESS))
                .thenReturn(Optional.empty());
        when(shelfRepository.findFirstByRole(Role.PICK))
                .thenReturn(Optional.of(pickShelf));

        IllegalStateException ex = assertThrows(
                IllegalStateException.class,
                () -> robotNavService.getPickPose("robot-1")
        );

        assertTrue(ex.getMessage().contains("Shelf has null map coords"));
    }

    // helpers

    private Shelf shelf(Integer id, String shelfCode, Role role, Double x, Double y, Double yaw) {
        Shelf shelf = new Shelf();
        setField(shelf, id, "id", "shelfId");
        setField(shelf, shelfCode, "shelfCode");
        setField(shelf, role, "role");
        setField(shelf, x, "mapX");
        setField(shelf, y, "mapY");
        setField(shelf, yaw, "mapYaw");
        return shelf;
    }

    private ShelfSlot slot(Integer id, Shelf shelf) {
        ShelfSlot slot = new ShelfSlot();
        setField(slot, id, "id", "slotId");
        setField(slot, shelf, "shelf");
        return slot;
    }

    private Task task(Integer id, Type type, Status status, String robotId, ShelfSlot sourceSlot, ShelfSlot targetSlot) {
        Task task = new Task();
        setField(task, id, "id", "taskId");
        setField(task, type, "type");
        setField(task, status, "status");
        setField(task, robotId, "robotId");
        setField(task, sourceSlot, "sourceSlot");
        setField(task, targetSlot, "targetSlot");
        return task;
    }

    private void assertPose(NavPoseResponse response, Double x, Double y, Double yaw) {
        assertEquals(x, getField(response, "x", "mapX"));
        assertEquals(y, getField(response, "y", "mapY"));
        assertEquals(yaw, getField(response, "yaw", "mapYaw"));
    }

    @SuppressWarnings("unchecked")
    private static <T> T getField(Object target, String... fieldNames) {
        for (String fieldName : fieldNames) {
            try {
                return (T) ReflectionTestUtils.getField(target, fieldName);
            } catch (IllegalArgumentException ignored) {
            }
        }
        throw new IllegalArgumentException("Field not found in " + target.getClass().getSimpleName());
    }

    private static void setField(Object target, Object value, String... fieldNames) {
        for (String fieldName : fieldNames) {
            try {
                ReflectionTestUtils.setField(target, fieldName, value);
                return;
            } catch (IllegalArgumentException ignored) {
            }
        }
        throw new IllegalArgumentException("Field not found in " + target.getClass().getSimpleName());
    }
}