package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.DeliveryTaskResponse;
import com.diploma.robot_warehouse_backend.entity.Outbound;
import com.diploma.robot_warehouse_backend.entity.OutboundLine;
import com.diploma.robot_warehouse_backend.entity.Product;
import com.diploma.robot_warehouse_backend.entity.Shelf;
import com.diploma.robot_warehouse_backend.entity.ShelfSlot;
import com.diploma.robot_warehouse_backend.entity.SlotState;
import com.diploma.robot_warehouse_backend.entity.Task;
import com.diploma.robot_warehouse_backend.enums.Role;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.enums.Type;
import com.diploma.robot_warehouse_backend.mapper.DeliveryTaskMapper;
import com.diploma.robot_warehouse_backend.repository.ShelfRepository;
import com.diploma.robot_warehouse_backend.repository.SlotStateRepository;
import com.diploma.robot_warehouse_backend.repository.TaskRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class DeliveryDispatchServiceTest {

    @Mock
    private TaskRepository taskRepository;

    @Mock
    private SlotStateRepository slotStateRepository;

    @Mock
    private ShelfRepository shelfRepository;

    @Mock
    private DeliveryTaskMapper deliveryTaskMapper;

    @InjectMocks
    private DeliveryDispatchService deliveryDispatchService;

    @Test
    @DisplayName("getNextDeliveryTask: должен зарезервировать оба слота, перевести задачу в IN_PROGRESS и вернуть response")
    void getNextDeliveryTask_shouldReserveBothSlotsAndReturnResponse() {
        String robotId = "robot-1";

        Product product = product(100);
        Task task = task(1, Type.DELIVERY, Status.NEW, product, null, null, null);

        ShelfSlot sourceSlot = slot(10);
        ShelfSlot targetSlot = slot(20);

        SlotState sourceState = slotState(sourceSlot, true, false, null, product, "SKU/MFG");
        SlotState targetState = slotState(targetSlot, false, false, null, null, null);

        Shelf deliveryShelf = shelf(5, Role.DELIVERY);
        DeliveryTaskResponse response = mock(DeliveryTaskResponse.class);

        when(taskRepository.findNextNewDeliveryForUpdate()).thenReturn(Optional.of(task));
        when(slotStateRepository.findOldestOccupiedStorageByProductIdForUpdate(100))
                .thenReturn(Optional.of(sourceState));
        when(slotStateRepository.findFirstFreeDeliveryUpperForUpdate())
                .thenReturn(Optional.of(targetState));
        when(shelfRepository.findFirstByRole(Role.DELIVERY))
                .thenReturn(Optional.of(deliveryShelf));
        when(deliveryTaskMapper.toResponse(task, deliveryShelf)).thenReturn(response);

        when(slotStateRepository.save(any(SlotState.class))).thenAnswer(inv -> inv.getArgument(0));
        when(taskRepository.save(any(Task.class))).thenAnswer(inv -> inv.getArgument(0));

        Optional<DeliveryTaskResponse> result = deliveryDispatchService.getNextDeliveryTask(robotId);

        assertTrue(result.isPresent());
        assertSame(response, result.get());

        assertEquals(Status.IN_PROGRESS, getField(task, "status"));
        assertEquals(robotId, getField(task, "robotId"));
        assertSame(sourceSlot, getField(task, "sourceSlot"));
        assertSame(targetSlot, getField(task, "targetSlot"));
        assertNotNull(getField(task, "updatedAt"));

        assertEquals(true, getField(sourceState, "reserved"));
        assertEquals(Integer.valueOf(1), getField(sourceState, "reservedTaskId"));
        assertNotNull(getField(sourceState, "updatedAt"));

        assertEquals(true, getField(targetState, "reserved"));
        assertEquals(Integer.valueOf(1), getField(targetState, "reservedTaskId"));
        assertNotNull(getField(targetState, "updatedAt"));

        verify(slotStateRepository).save(sourceState);
        verify(slotStateRepository).save(targetState);
        verify(taskRepository).save(task);
        verify(deliveryTaskMapper).toResponse(task, deliveryShelf);
    }

    @Test
    @DisplayName("getNextDeliveryTask: если новой задачи нет, должен вернуть Optional.empty")
    void getNextDeliveryTask_shouldReturnEmptyWhenNoTask() {
        when(taskRepository.findNextNewDeliveryForUpdate()).thenReturn(Optional.empty());

        Optional<DeliveryTaskResponse> result = deliveryDispatchService.getNextDeliveryTask("robot-1");

        assertTrue(result.isEmpty());

        verify(taskRepository).findNextNewDeliveryForUpdate();
        verifyNoMoreInteractions(slotStateRepository, shelfRepository, deliveryTaskMapper);
    }

    @Test
    @DisplayName("getNextDeliveryTask: если у DELIVERY-задачи нет product, должен выбросить исключение")
    void getNextDeliveryTask_shouldThrowWhenTaskHasNoProduct() {
        Task task = task(1, Type.DELIVERY, Status.NEW, null, null, null, null);
        when(taskRepository.findNextNewDeliveryForUpdate()).thenReturn(Optional.of(task));

        IllegalStateException ex = assertThrows(
                IllegalStateException.class,
                () -> deliveryDispatchService.getNextDeliveryTask("robot-1")
        );

        assertTrue(ex.getMessage().contains("DELIVERY task has no product"));
        verify(taskRepository).findNextNewDeliveryForUpdate();
        verifyNoMoreInteractions(slotStateRepository, shelfRepository, deliveryTaskMapper);
    }

    @Test
    @DisplayName("completeDeliveryTask(success=true): должен освободить STORAGE, занять DELIVERY и перевести задачу в WAITING_PICKUP")
    void completeDeliveryTask_shouldMoveProductToDeliveryWhenSuccess() {
        String robotId = "robot-1";

        Product product = product(100);
        ShelfSlot sourceSlot = slot(10);
        ShelfSlot targetSlot = slot(20);

        Task task = task(1, Type.DELIVERY, Status.IN_PROGRESS, product, robotId, sourceSlot, targetSlot);

        SlotState sourceState = slotState(sourceSlot, true, true, 1, product, "SKU/MFG");
        setField(sourceState, LocalDateTime.now().minusHours(1), "storedAt");

        SlotState targetState = slotState(targetSlot, false, true, 1, null, null);

        when(taskRepository.findById(1)).thenReturn(Optional.of(task));
        when(slotStateRepository.findById(10)).thenReturn(Optional.of(sourceState));
        when(slotStateRepository.findById(20)).thenReturn(Optional.of(targetState));

        when(slotStateRepository.save(any(SlotState.class))).thenAnswer(inv -> inv.getArgument(0));
        when(taskRepository.save(any(Task.class))).thenAnswer(inv -> inv.getArgument(0));

        deliveryDispatchService.completeDeliveryTask(1, robotId, true);

        assertEquals(false, getField(sourceState, "reserved"));
        assertNull(getField(sourceState, "reservedTaskId"));
        assertEquals(false, getField(sourceState, "occupied"));
        assertNull(getField(sourceState, "product"));
        assertNull(getField(sourceState, "storedAt"));
        assertNull(getField(sourceState, "cubeQr"));
        assertEquals(robotId, getField(sourceState, "robotId"));
        assertNotNull(getField(sourceState, "updatedAt"));

        assertEquals(false, getField(targetState, "reserved"));
        assertNull(getField(targetState, "reservedTaskId"));
        assertEquals(true, getField(targetState, "occupied"));
        assertSame(product, getField(targetState, "product"));
        assertEquals(robotId, getField(targetState, "robotId"));
        assertNotNull(getField(targetState, "storedAt"));
        assertNotNull(getField(targetState, "updatedAt"));

        assertEquals(Status.WAITING_PICKUP, getField(task, "status"));
        assertNotNull(getField(task, "updatedAt"));

        verify(slotStateRepository).save(sourceState);
        verify(slotStateRepository).save(targetState);
        verify(taskRepository).save(task);
    }

    @Test
    @DisplayName("completeDeliveryTask(success=false): должен снять резервы и перевести задачу в ERROR")
    void completeDeliveryTask_shouldSetErrorWhenDeliveryFailed() {
        String robotId = "robot-1";

        Product product = product(100);
        ShelfSlot sourceSlot = slot(10);
        ShelfSlot targetSlot = slot(20);

        Task task = task(1, Type.DELIVERY, Status.IN_PROGRESS, product, robotId, sourceSlot, targetSlot);

        SlotState sourceState = slotState(sourceSlot, true, true, 1, product, "SKU/MFG");
        setField(sourceState, LocalDateTime.now().minusHours(1), "storedAt");

        SlotState targetState = slotState(targetSlot, false, true, 1, null, null);

        when(taskRepository.findById(1)).thenReturn(Optional.of(task));
        when(slotStateRepository.findById(10)).thenReturn(Optional.of(sourceState));
        when(slotStateRepository.findById(20)).thenReturn(Optional.of(targetState));

        when(slotStateRepository.save(any(SlotState.class))).thenAnswer(inv -> inv.getArgument(0));
        when(taskRepository.save(any(Task.class))).thenAnswer(inv -> inv.getArgument(0));

        deliveryDispatchService.completeDeliveryTask(1, robotId, false);

        assertEquals(false, getField(sourceState, "reserved"));
        assertNull(getField(sourceState, "reservedTaskId"));
        assertEquals(true, getField(sourceState, "occupied"));
        assertSame(product, getField(sourceState, "product"));
        assertEquals(robotId, getField(sourceState, "robotId"));

        assertEquals(false, getField(targetState, "reserved"));
        assertNull(getField(targetState, "reservedTaskId"));
        assertEquals(false, getField(targetState, "occupied"));
        assertNull(getField(targetState, "product"));
        assertEquals(robotId, getField(targetState, "robotId"));

        assertEquals(Status.ERROR, getField(task, "status"));
        assertNotNull(getField(task, "updatedAt"));

        verify(slotStateRepository).save(sourceState);
        verify(slotStateRepository).save(targetState);
        verify(taskRepository).save(task);
    }

    @Test
    @DisplayName("completeDeliveryTask: если задача принадлежит другому роботу, должен выбросить исключение")
    void completeDeliveryTask_shouldThrowWhenTaskOwnedByAnotherRobot() {
        Product product = product(100);
        Task task = task(1, Type.DELIVERY, Status.IN_PROGRESS, product, "robot-2", slot(10), slot(20));

        when(taskRepository.findById(1)).thenReturn(Optional.of(task));

        IllegalStateException ex = assertThrows(
                IllegalStateException.class,
                () -> deliveryDispatchService.completeDeliveryTask(1, "robot-1", true)
        );

        assertTrue(ex.getMessage().contains("owned by another robot"));

        verify(taskRepository).findById(1);
        verifyNoInteractions(slotStateRepository);
    }

    @Test
    @DisplayName("confirmPickup: должен очистить delivery slot, перевести задачи в DONE и outbound в DONE")
    void confirmPickup_shouldClearDeliverySlotsAndFinishOutbound() {
        Integer outboundId = 77;

        Product product1 = product(100);
        Product product2 = product(200);

        Outbound outbound = outbound(outboundId, Status.IN_PROGRESS);
        OutboundLine outboundLine = mock(OutboundLine.class);
        when(outboundLine.getOutbound()).thenReturn(outbound);

        ShelfSlot targetSlot1 = slot(20);
        ShelfSlot targetSlot2 = slot(21);

        Task task1 = task(1, Type.DELIVERY, Status.WAITING_PICKUP, product1, "robot-1", null, targetSlot1);
        Task task2 = task(2, Type.DELIVERY, Status.WAITING_PICKUP, product2, "robot-1", null, targetSlot2);

        setField(task1, outboundLine, "outboundLine");
        setField(task2, outboundLine, "outboundLine");

        SlotState targetState1 = slotState(targetSlot1, true, false, null, product1, "QR-1");
        setField(targetState1, LocalDateTime.now().minusMinutes(10), "storedAt");

        SlotState targetState2 = slotState(targetSlot2, true, false, null, product2, "QR-2");
        setField(targetState2, LocalDateTime.now().minusMinutes(5), "storedAt");

        when(taskRepository.findByOutboundLine_Outbound_IdAndStatus(outboundId, Status.WAITING_PICKUP))
                .thenReturn(List.of(task1, task2));

        when(slotStateRepository.findById(20)).thenReturn(Optional.of(targetState1));
        when(slotStateRepository.findById(21)).thenReturn(Optional.of(targetState2));

        when(taskRepository.existsByOutboundLine_Outbound_IdAndStatusIn(eq(outboundId), anyList()))
                .thenReturn(false);

        when(slotStateRepository.save(any(SlotState.class))).thenAnswer(inv -> inv.getArgument(0));
        when(taskRepository.save(any(Task.class))).thenAnswer(inv -> inv.getArgument(0));

        deliveryDispatchService.confirmPickup(outboundId);

        assertEquals(false, getField(targetState1, "reserved"));
        assertNull(getField(targetState1, "reservedTaskId"));
        assertEquals(false, getField(targetState1, "occupied"));
        assertNull(getField(targetState1, "product"));
        assertNull(getField(targetState1, "storedAt"));
        assertNull(getField(targetState1, "cubeQr"));

        assertEquals(false, getField(targetState2, "reserved"));
        assertNull(getField(targetState2, "reservedTaskId"));
        assertEquals(false, getField(targetState2, "occupied"));
        assertNull(getField(targetState2, "product"));
        assertNull(getField(targetState2, "storedAt"));
        assertNull(getField(targetState2, "cubeQr"));

        assertEquals(Status.DONE, getField(task1, "status"));
        assertEquals(Status.DONE, getField(task2, "status"));
        assertEquals(Status.DONE, getField(outbound, "status"));

        verify(slotStateRepository, times(2)).save(any(SlotState.class));
        verify(taskRepository, times(2)).save(any(Task.class));
    }

    @Test
    @DisplayName("confirmPickup: если WAITING_PICKUP задач нет, должен выбросить исключение")
    void confirmPickup_shouldThrowWhenNoWaitingTasks() {
        Integer outboundId = 77;

        when(taskRepository.findByOutboundLine_Outbound_IdAndStatus(outboundId, Status.WAITING_PICKUP))
                .thenReturn(List.of());

        IllegalStateException ex = assertThrows(
                IllegalStateException.class,
                () -> deliveryDispatchService.confirmPickup(outboundId)
        );

        assertTrue(ex.getMessage().contains("No WAITING_PICKUP tasks"));
        verify(taskRepository).findByOutboundLine_Outbound_IdAndStatus(outboundId, Status.WAITING_PICKUP);
        verifyNoInteractions(slotStateRepository);
    }

    // ------------------ helpers ------------------

    private Product product(int id) {
        Product product = new Product();
        setField(product, id, "id", "productId");
        setField(product, "SKU-" + id, "sku");
        setField(product, "MFG-" + id, "manufacturer");
        setField(product, "Product-" + id, "name");
        return product;
    }

    private Shelf shelf(int id, Role role) {
        Shelf shelf = new Shelf();
        setField(shelf, id, "id", "shelfId");
        setField(shelf, "DELIVERY-01", "shelfCode");
        setField(shelf, role, "role");
        return shelf;
    }

    private ShelfSlot slot(int id) {
        ShelfSlot slot = new ShelfSlot();
        setField(slot, id, "id", "Id", "slotId");
        setField(slot, true, "enabled");
        return slot;
    }

    private SlotState slotState(ShelfSlot slot,
                                boolean occupied,
                                boolean reserved,
                                Integer reservedTaskId,
                                Product product,
                                String cubeQr) {
        SlotState state = new SlotState();

        Integer slotId = getField(slot, "id", "Id", "slotId");
        setField(state, slotId, "slotId", "id");
        setField(state, slot, "slot");
        setField(state, occupied, "occupied");
        setField(state, reserved, "reserved");
        setField(state, reservedTaskId, "reservedTaskId");
        setField(state, product, "product");
        setField(state, cubeQr, "cubeQr");
        setField(state, null, "storedAt");
        setField(state, null, "robotId");
        setField(state, null, "updatedAt");

        return state;
    }

    private Task task(Integer id,
                      Type type,
                      Status status,
                      Product product,
                      String robotId,
                      ShelfSlot sourceSlot,
                      ShelfSlot targetSlot) {
        Task task = new Task();
        setField(task, id, "id");
        setField(task, type, "type");
        setField(task, status, "status");
        setField(task, product, "product");
        setField(task, robotId, "robotId");
        setField(task, sourceSlot, "sourceSlot");
        setField(task, targetSlot, "targetSlot");
        setField(task, null, "updatedAt");
        return task;
    }

    private Outbound outbound(Integer id, Status status) {
        Outbound outbound = new Outbound();
        setField(outbound, id, "id", "outboundId");
        setField(outbound, status, "status");
        return outbound;
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