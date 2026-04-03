package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.dto.OutboundCreateRequest;
import com.diploma.robot_warehouse_backend.dto.OutboundCreateResult;
import com.diploma.robot_warehouse_backend.dto.OutboundItemRequest;
import com.diploma.robot_warehouse_backend.entity.Product;
import com.diploma.robot_warehouse_backend.repository.ProductRepository;
import com.diploma.robot_warehouse_backend.service.DeliveryDispatchService;
import com.diploma.robot_warehouse_backend.service.OutboundService;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.ArrayList;
import java.util.List;

@Controller
@RequestMapping("/outbounds")
public class OutboundUiController {
    private final OutboundService outboundService;
    private final ProductRepository productRepository;
    private final DeliveryDispatchService deliveryDispatchService;

    public OutboundUiController(OutboundService outboundService, ProductRepository productRepository, DeliveryDispatchService deliveryDispatchService) {
        this.outboundService = outboundService;
        this.productRepository = productRepository;
        this.deliveryDispatchService = deliveryDispatchService;
    }

    @GetMapping("/create")
    public String createForm(@RequestParam(required = false) String q, Model model) {
        List<Product> products = productRepository.findInStockByNameLike(q);
        model.addAttribute("q", q == null ? "" : q);
        model.addAttribute("products", products);
        return "outbounds/create";
    }

    @PostMapping("/create")
    public String create(@RequestParam String externalRef,
                         @RequestParam(name = "productId") List<Integer> productIds,
                         @RequestParam(name = "quantity") List<Integer> quantities,
                         Model model) {
        try {
            if (productIds == null || productIds.isEmpty()) {
                throw new IllegalArgumentException("Выберите хотя бы один товар");
            }

            if (quantities == null || quantities.isEmpty()) {
                throw new IllegalArgumentException("Укажите количество");
            }

            if (productIds.size() != quantities.size()) {
                throw new IllegalArgumentException("Некорректные данные корзины");
            }

            List<OutboundItemRequest> items = new ArrayList<>();
            for (int i = 0; i < productIds.size(); i++) {
                OutboundItemRequest item = new OutboundItemRequest();
                item.setProductId(productIds.get(i));
                item.setQuantity(quantities.get(i));
                items.add(item);
            }

            OutboundCreateRequest request = new OutboundCreateRequest();
            request.setExternalRef(externalRef);
            request.setItems(items);

            OutboundCreateResult result = outboundService.createOutbound(request);
            model.addAttribute("outboundId", result.getOutboundId());
            model.addAttribute(
                    "ok",
                    "Outbound created. id=" + result.getOutboundId()
                            + ", lines=" + result.getLinesCreated()
                            + ", tasks=" + result.getTasksCreated()
            );
        } catch (Exception e) {
            model.addAttribute("error", "Error: " + e.getMessage());
        }

        model.addAttribute("q", "");
        model.addAttribute("products", productRepository.findInStockByNameLike(""));
        return "outbounds/create";
    }

    @PostMapping("/pickup-confirm")
    public String confirmPickup(
            @RequestParam Integer outboundId,
            Model model) {

        try {
            deliveryDispatchService.confirmPickup(outboundId);
            model.addAttribute("outboundId", outboundId);
            model.addAttribute(
                    "ok",
                    "Товары забраны. Delivery-слоты освобождены."
            );

        } catch (Exception e) {
            model.addAttribute("outboundId", outboundId);
            model.addAttribute(
                    "error",
                    "Ошибка при подтверждении выдачи: " + e.getMessage()
            );
        }

        model.addAttribute("q", "");
        model.addAttribute(
                "products",
                productRepository.findInStockByNameLike("")
        );

        return "outbounds/create";
    }
}